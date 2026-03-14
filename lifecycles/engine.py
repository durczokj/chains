"""
Graph-based lifecycle engine.

Domain rules (processed per code type independently):
- Introduction  → creates a new product family with its first generation
- PIPO          → adds a new generation to an existing family (PI replaces PO)
- Discontinuation → ends an existing generation

The engine uses NetworkX to build a DAG of generations linked by PIPO events,
then persists the result.
"""

import datetime

import networkx as nx

from events.models import CodeTransition, CodeType, TransitionType
from lifecycles.models import (
    Generation,
    GenerationLink,
    ProductFamily,
)


def recompute_lifecycles(iso_country_code=None):
    """Recompute all lifecycles, optionally scoped to a single country."""
    qs = CodeTransition.objects.select_related("event")
    if iso_country_code:
        qs = qs.filter(event__iso_country_code=iso_country_code)

    countries = list(
        qs.values_list("event__iso_country_code", flat=True).distinct()
    )

    for country in countries:
        _recompute_country(country)


def _recompute_country(country):
    """Recompute lifecycles for a single country, per code type."""
    # Clear existing data for this country
    ProductFamily.objects.filter(iso_country_code=country).delete()

    # Get all code types that have transitions in this country
    code_type_ids = list(
        CodeTransition.objects.filter(event__iso_country_code=country)
        .values_list("code_type_id", flat=True)
        .distinct()
    )

    for code_type_id in code_type_ids:
        _recompute_country_code_type(country, code_type_id)


def _recompute_country_code_type(country, code_type_id):
    """Recompute chains for a single country + code type combination.

    Algorithm:
    1. Introduction → new generation (start_date = event date, end_date = 9999-12-31)
    2. Discontinuation → set end_date on the generation matching po_code
    3. PIPO → link the po_code generation to the pi_code generation
    """
    # Order: by date, then within the same event process INTRO first, PIPO second, DISCONT last
    TYPE_ORDER = {TransitionType.INTRODUCTION: 0, TransitionType.PIPO: 1, TransitionType.DISCONTINUATION: 2}

    transitions = list(
        CodeTransition.objects.filter(
            event__iso_country_code=country,
            code_type_id=code_type_id,
        )
        .select_related("event", "introduction", "discontinuation", "pipo")
        .order_by("event__date", "event__pk", "pk")
    )

    transitions.sort(key=lambda ct: (ct.event.date, ct.event.pk, TYPE_ORDER.get(ct.type, 9), ct.pk))

    if not transitions:
        return

    G = nx.DiGraph()
    active_by_code = {}  # code → node_id
    node_counter = 0

    for ct in transitions:
        evt = ct.event

        if ct.type == TransitionType.INTRODUCTION:
            node_id = node_counter
            node_counter += 1
            G.add_node(node_id,
                       transition_id=ct.id,
                       code=ct.introduction.pi_code,
                       start_date=evt.date,
                       end_date=datetime.date(9999, 12, 31))
            active_by_code[ct.introduction.pi_code] = node_id

        elif ct.type == TransitionType.DISCONTINUATION:
            pred = active_by_code.get(ct.discontinuation.po_code)
            if pred is not None:
                G.nodes[pred]["end_date"] = evt.date
                del active_by_code[ct.discontinuation.po_code]

        elif ct.type == TransitionType.PIPO:
            pred = active_by_code.get(ct.pipo.po_code)
            succ = active_by_code.get(ct.pipo.pi_code)
            if pred is not None and succ is not None:
                G.add_edge(pred, succ, transition_id=ct.id, event_date=evt.date)

    # --- Persist ---
    # Each weakly connected component is a product family
    node_to_gen = {}
    for family_idx, component in enumerate(nx.weakly_connected_components(G), start=1):
        pf = ProductFamily.objects.create(
            code_type_id=code_type_id,
            identifier=f"{country}-{code_type_id}-{family_idx:04d}",
            iso_country_code=country,
        )

        for node_id in sorted(component, key=lambda n: G.nodes[n]["start_date"]):
            data = G.nodes[node_id]
            gen = Generation.objects.create(
                product_family=pf,
                source_transition_id=data["transition_id"],
                code=data["code"],
                iso_country_code=country,
                start_date=data["start_date"],
                end_date=data["end_date"],
            )
            node_to_gen[node_id] = gen

    for u, v, edata in G.edges(data=True):
        GenerationLink.objects.create(
            predecessor=node_to_gen[u],
            successor=node_to_gen[v],
            source_transition_id=edata.get("transition_id"),
        )

    _check_generation_overlaps(country, code_type_id)


def _check_generation_overlaps(country, code_type_id):
    """Raise ValidationError if any two generations for the same code overlap in time."""
    from django.core.exceptions import ValidationError

    gens = (
        Generation.objects.filter(
            iso_country_code=country,
            product_family__code_type_id=code_type_id,
        )
        .order_by("code", "start_date")
        .values_list("code", "start_date", "end_date")
    )

    prev_code, prev_end = None, None
    for code, start, end in gens:
        if code == prev_code and start < prev_end:
            raise ValidationError(
                f"Overlapping generations for code {code} "
                f"(code type {code_type_id}, country {country})."
            )
        prev_code = code
        prev_end = end


def get_product_family_mermaid(product_family_id):
    """Return a Mermaid graph definition for a product family's DAG."""
    pf = ProductFamily.objects.get(pk=product_family_id)
    generations = pf.generations.all()
    links = GenerationLink.objects.filter(
        predecessor__product_family=pf, successor__product_family=pf
    ).select_related("source_transition__event")

    lines = ["graph LR"]
    for gen in generations:
        label = f"Code {gen.code}<br/>{gen.start_date} – {gen.end_date}"
        lines.append(f'    G{gen.pk}["{label}"]')

    for lnk in links:
        if lnk.source_transition:
            date = lnk.source_transition.event.date
            lines.append(f'    G{lnk.predecessor_id} -->|"{date}"| G{lnk.successor_id}')
        else:
            lines.append(f"    G{lnk.predecessor_id} --> G{lnk.successor_id}")

    return "\n".join(lines)
