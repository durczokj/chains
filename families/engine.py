"""
Graph-based family engine.

Domain rules (processed per code type independently):
- Introduction  → creates a new product family with its first generation
- chain          → adds a new generation to an existing family (PI replaces PO)
- Discontinuation → ends an existing generation

The engine uses NetworkX to build a DAG of generations linked by chain events,
then persists the result using bulk operations for speed.
"""

import datetime
import time
from collections import defaultdict

import networkx as nx
from django.core.exceptions import ValidationError
from django.db import transaction

from events.models import CodeTransition, TransitionType
from families.models import (
    Generation,
    GenerationLink,
    ProductFamily,
)


def recompute_families(iso_country_code=None):
    """Recompute all families, optionally scoped to a single country."""
    qs = CodeTransition.objects.all()
    if iso_country_code:
        qs = qs.filter(event__iso_country_code=iso_country_code)

    countries = list(set(qs.values_list("event__iso_country_code", flat=True)))

    for country in countries:
        _recompute_country(country)


def _recompute_country(country):
    """Recompute families for a single country, per code type."""
    t0 = time.perf_counter()
    with transaction.atomic():
        t1 = time.perf_counter()
        ProductFamily.objects.filter(iso_country_code=country).delete()
        t2 = time.perf_counter()
        print(f"  [{country}] delete old families: {t2-t1:.3f}s")

        code_type_ids = list(
            set(
                CodeTransition.objects.filter(event__iso_country_code=country).values_list(
                    "code_type_id", flat=True
                )
            )
        )
        t3 = time.perf_counter()
        print(f"  [{country}] find code types ({len(code_type_ids)}): {t3-t2:.3f}s")

        for code_type_id in code_type_ids:
            _recompute_country_code_type(country, code_type_id)
    print(f"  [{country}] TOTAL: {time.perf_counter()-t0:.3f}s")


def _recompute_country_code_type(country, code_type_id):
    """Recompute chains for a single country + code type combination.

    Uses bulk_create for all DB writes to minimise round-trips.
    """
    TYPE_ORDER: dict[str, int] = {
        TransitionType.INTRODUCTION: 0,
        TransitionType.chain: 1,
        TransitionType.DISCONTINUATION: 2,
    }

    t_start = time.perf_counter()
    transitions = list(
        CodeTransition.objects.filter(
            event__iso_country_code=country,
            code_type_id=code_type_id,
        )
        .select_related("introduction", "discontinuation", "chain")
        .order_by("date", "pk")
    )
    transitions.sort(key=lambda ct: (ct.date, TYPE_ORDER.get(ct.type, 9), ct.pk))
    t_query = time.perf_counter()
    print(
        f"    [{country}/{code_type_id}] query {len(transitions)}"
        f" transitions: {t_query - t_start:.3f}s"
    )

    if not transitions:
        return

    # ── Build the in-memory graph ────────────────────────────────────
    G = nx.DiGraph()
    active_by_code = {}
    last_by_code = {}
    node_counter = 0
    unresolved = []

    for ct in transitions:
        if ct.type == TransitionType.INTRODUCTION:
            node_id = node_counter
            node_counter += 1
            G.add_node(
                node_id,
                intro_ct=ct,
                disco_ct=None,
                code=ct.introduction.introduction_code,
                start_date=ct.date,
                end_date=datetime.date(9999, 12, 31),
            )
            active_by_code[ct.introduction.introduction_code] = node_id
            last_by_code[ct.introduction.introduction_code] = node_id

        elif ct.type == TransitionType.DISCONTINUATION:
            pred = active_by_code.get(ct.discontinuation.discontinuation_code)
            if pred is not None:
                G.nodes[pred]["end_date"] = ct.date
                G.nodes[pred]["disco_ct"] = ct
                del active_by_code[ct.discontinuation.discontinuation_code]
            else:
                unresolved.append(
                    (
                        ct,
                        f"Discontinuation of code {ct.discontinuation.discontinuation_code} "
                        f"which has no active generation",
                    )
                )

        elif ct.type == TransitionType.chain:
            pred = last_by_code.get(ct.chain.discontinuation_code)
            succ = active_by_code.get(ct.chain.introduction_code)
            if pred is None:
                unresolved.append(
                    (
                        ct,
                        f"Chain references discontinuation code {ct.chain.discontinuation_code} "
                        f"which has no generation",
                    )
                )
            elif succ is None:
                unresolved.append(
                    (
                        ct,
                        f"Chain references introduction code {ct.chain.introduction_code} "
                        f"which has no active generation",
                    )
                )
            else:
                G.add_edge(pred, succ, transition_id=ct.id, event_date=ct.date)

    t_graph = time.perf_counter()
    print(
        f"    [{country}/{code_type_id}] build graph"
        f" ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges):"
        f" {t_graph - t_query:.3f}s"
    )

    # ── Validate in-memory (before writing anything) ─────────────────
    _check_unresolved_transitions(unresolved, country, code_type_id)
    _check_generation_overlaps_from_graph(G, country, code_type_id)
    t_validate = time.perf_counter()
    print(f"    [{country}/{code_type_id}] validate: {t_validate-t_graph:.3f}s")

    # ── Bulk-persist ─────────────────────────────────────────────────
    # 1. ProductFamilies — one per weakly connected component
    components = list(nx.weakly_connected_components(G))
    pf_objs = ProductFamily.objects.bulk_create(
        [
            ProductFamily(
                code_type_id=code_type_id,
                identifier=f"{country}-{code_type_id}-{idx:04d}",
                iso_country_code=country,
            )
            for idx, _comp in enumerate(components, start=1)
        ]
    )

    # 2. Generations — bulk create, keyed by node_id
    gen_objs_flat: list[Generation] = []
    node_to_idx: dict[int, int] = {}  # node_id → position in gen_objs_flat
    for pf, component in zip(pf_objs, components):
        for node_id in sorted(component, key=lambda n: G.nodes[n]["start_date"]):
            data = G.nodes[node_id]
            node_to_idx[node_id] = len(gen_objs_flat)
            gen_objs_flat.append(
                Generation(
                    product_family=pf,
                    introduction=data["intro_ct"],
                    discontinuation=data["disco_ct"],
                    code=data["code"],
                    iso_country_code=country,
                )
            )

    created_gens = Generation.objects.bulk_create(gen_objs_flat)

    # 3. GenerationLinks — bulk create
    link_objs = []
    for u, v, edata in G.edges(data=True):
        link_objs.append(
            GenerationLink(
                predecessor=created_gens[node_to_idx[u]],
                successor=created_gens[node_to_idx[v]],
                source_transition_id=edata.get("transition_id"),
            )
        )
    if link_objs:
        GenerationLink.objects.bulk_create(link_objs)
    t_persist = time.perf_counter()
    print(
        f"    [{country}/{code_type_id}] bulk persist"
        f" ({len(pf_objs)} families, {len(gen_objs_flat)} gens,"
        f" {len(link_objs)} links): {t_persist - t_validate:.3f}s"
    )


def _check_generation_overlaps_from_graph(G, country, code_type_id):
    """Check for overlapping generations purely from the in-memory graph."""
    by_code = defaultdict(list)
    for _node_id, data in G.nodes(data=True):
        by_code[data["code"]].append((data["start_date"], data["end_date"]))

    for code, intervals in by_code.items():
        intervals.sort()
        for i in range(1, len(intervals)):
            if intervals[i][0] < intervals[i - 1][1]:
                raise ValidationError(
                    f"Overlapping generations for code {code} "
                    f"(code type {code_type_id}, country {country})."
                )


def _check_unresolved_transitions(unresolved, country, code_type_id):
    """Raise ValidationError if any transitions could not be resolved."""
    if unresolved:
        msgs = [reason for _ct, reason in unresolved]
        raise ValidationError(msgs)


def get_product_family_mermaid(product_family_id):
    """Return a Mermaid graph definition for a product family's DAG."""
    pf = ProductFamily.objects.get(pk=product_family_id)
    generations = pf.generations.select_related("introduction", "discontinuation").all()
    links = GenerationLink.objects.filter(
        predecessor__product_family=pf, successor__product_family=pf
    ).select_related("source_transition")

    lines = ["graph LR"]
    for gen in generations:
        label = f"Code {gen.code}<br/>{gen.start_date} – {gen.end_date}"
        lines.append(f'    G{gen.pk}["{label}"]')

    for lnk in links:
        if lnk.source_transition:
            date = lnk.source_transition.date
            lines.append(f'    G{lnk.predecessor_id} -->|"{date}"| G{lnk.successor_id}')
        else:
            lines.append(f"    G{lnk.predecessor_id} --> G{lnk.successor_id}")

    return "\n".join(lines)
