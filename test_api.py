#!/usr/bin/env python3
"""
API stress test for chain.

Creates familys via the REST API with at least 3 products each,
covering chain, one-to-many, many-to-one, and long-chain scenarios,
plus deliberate failure cases.

Usage:
    python test_api.py [options]

Run with --help for all options.
"""

import argparse
import json
import random
import time
from datetime import date, timedelta
from pathlib import Path
from typing import TextIO

import requests

# ── Defaults ──────────────────────────────────────────────────────────
DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_LOG_PATH = "api_test_log.jsonl"
DEFAULT_TOTAL = 10_000
DEFAULT_COUNTRIES = ["PL", "DE", "FR", "GB", "US", "JP", "BR", "AU", "CA", "IT"]
DEFAULT_CODE_TYPE_ID = "NTN"

# ── Runtime globals (set from CLI args in main) ───────────────────────
BASE_URL = DEFAULT_BASE_URL
LOG_PATH = Path(DEFAULT_LOG_PATH)
TOTAL_FAMILIES = DEFAULT_TOTAL
COUNTRIES = list(DEFAULT_COUNTRIES)
CODE_TYPE_ID = DEFAULT_CODE_TYPE_ID

# ── State ─────────────────────────────────────────────────────────────
_code_seq = 1_000_000
_session = requests.Session()
_log_fh: TextIO | None = None
stats = {"success": 0, "expected_fail": 0, "unexpected_fail": 0}


def next_code():
    global _code_seq
    _code_seq += 1
    return _code_seq


def rand_date(y_lo=2020, y_hi=2025):
    start = date(y_lo, 1, 1)
    return start + timedelta(days=random.randint(0, (date(y_hi, 12, 31) - start).days))


def rand_date_sequence(n, y_lo=2020, y_hi=2025):
    """Return a sorted list of *n* distinct random dates."""
    result: set[date] = set()
    start = date(y_lo, 1, 1)
    span = (date(y_hi, 12, 31) - start).days
    while len(result) < n:
        result.add(start + timedelta(days=random.randint(0, span)))
    return sorted(result)


# ── Logging ───────────────────────────────────────────────────────────
def _log(label, method, url, payload, resp):
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "label": label,
        "method": method,
        "url": url,
        "request": payload,
        "status": resp.status_code,
        "response": body,
    }
    assert _log_fh is not None
    _log_fh.write(json.dumps(entry, default=str) + "\n")
    _log_fh.flush()


# ── HTTP helpers ──────────────────────────────────────────────────────
def post(label, path, data, *, expect_ok=True):
    url = f"{BASE_URL}{path}"
    r = _session.post(url, json=data)
    _log(label, "POST", url, data, r)
    if r.status_code in (200, 201):
        stats["success"] += 1
    elif not expect_ok and r.status_code >= 400:
        stats["expected_fail"] += 1
    else:
        stats["unexpected_fail"] += 1
    return r


def delete(label, path, *, expect_ok=True):
    url = f"{BASE_URL}{path}"
    r = _session.delete(url)
    _log(label, "DELETE", url, None, r)
    if r.status_code in (200, 204):
        stats["success"] += 1
    elif not expect_ok and r.status_code >= 400:
        stats["expected_fail"] += 1
    else:
        stats["unexpected_fail"] += 1
    return r


def get(label, path, params=None):
    url = f"{BASE_URL}{path}"
    r = _session.get(url, params=params)
    _log(label, "GET", url, params, r)
    return r


# ── Setup ─────────────────────────────────────────────────────────────
def setup():
    # Ensure countries exist
    for code in COUNTRIES:
        r = get(f"check_country_{code}", f"/api/countries/{code}/")
        if r.status_code == 404:
            post(f"create_country_{code}", "/api/countries/", {"code": code, "name": code})
    print(f"Countries ready: {COUNTRIES}")

    r = get("check_code_type", f"/api/code-types/{CODE_TYPE_ID}/")
    if r.status_code == 404:
        post("create_code_type", "/api/code-types/", {"id": CODE_TYPE_ID, "type": "National"})
    print(f"Code type '{CODE_TYPE_ID}' ready.")


# ── Delete all events ────────────────────────────────────────────────
def delete_all_events():
    """Delete every event via the REST API."""
    print("Deleting all events ...")
    deleted = 0
    while True:
        r = get("delete_list_events", "/api/events/", {"page_size": 100})
        if r.status_code != 200:
            print(f"  Could not list events (HTTP {r.status_code}), stopping.")
            break
        data = r.json()
        events = data.get("results", data) if isinstance(data, dict) else data
        if not events:
            break
        for ev in events:
            eid = ev["id"]
            delete(f"delete_event_{eid}", f"/api/events/{eid}/")
            deleted += 1
        if deleted % 500 == 0:
            print(f"  Deleted {deleted} events so far ...")
    print(f"  Deleted {deleted} events total.\n")


# ── Scenario builders ────────────────────────────────────────────────
# Each returns (list_of_single_transition_lists, scenario_tag).
# Every element in the outer list becomes a separate event (with its own date).


def scenario_chain3():
    """A → B → C  (simple chain of 3)"""
    a, b, c = next_code(), next_code(), next_code()
    return [
        [{"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": a}],
        [
            {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": b},
            {
                "code_type_id": CODE_TYPE_ID,
                "type": "chain",
                "introduction_code": b,
                "discontinuation_code": a,
            },
            {"code_type_id": CODE_TYPE_ID, "type": "DISCONT", "discontinuation_code": a},
        ],
        [
            {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": c},
            {
                "code_type_id": CODE_TYPE_ID,
                "type": "chain",
                "introduction_code": c,
                "discontinuation_code": b,
            },
            {"code_type_id": CODE_TYPE_ID, "type": "DISCONT", "discontinuation_code": b},
        ],
    ], "chain3"


def scenario_chain4():
    """A → B → C → D  (longer chain of 4)"""
    a, b, c, d = next_code(), next_code(), next_code(), next_code()
    return [
        [{"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": a}],
        [
            {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": b},
            {
                "code_type_id": CODE_TYPE_ID,
                "type": "chain",
                "introduction_code": b,
                "discontinuation_code": a,
            },
            {"code_type_id": CODE_TYPE_ID, "type": "DISCONT", "discontinuation_code": a},
        ],
        [
            {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": c},
            {
                "code_type_id": CODE_TYPE_ID,
                "type": "chain",
                "introduction_code": c,
                "discontinuation_code": b,
            },
            {"code_type_id": CODE_TYPE_ID, "type": "DISCONT", "discontinuation_code": b},
        ],
        [
            {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": d},
            {
                "code_type_id": CODE_TYPE_ID,
                "type": "chain",
                "introduction_code": d,
                "discontinuation_code": c,
            },
            {"code_type_id": CODE_TYPE_ID, "type": "DISCONT", "discontinuation_code": c},
        ],
    ], "chain4"


def scenario_one_to_many():
    """A → {B, C}  (one code splits into two)"""
    a, b, c = next_code(), next_code(), next_code()
    return [
        [{"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": a}],
        # First chain keeps A alive
        [
            {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": b},
            {
                "code_type_id": CODE_TYPE_ID,
                "type": "chain",
                "introduction_code": b,
                "discontinuation_code": a,
            },
        ],
        # Second chain discontinues A
        [
            {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": c},
            {
                "code_type_id": CODE_TYPE_ID,
                "type": "chain",
                "introduction_code": c,
                "discontinuation_code": a,
            },
            {"code_type_id": CODE_TYPE_ID, "type": "DISCONT", "discontinuation_code": a},
        ],
    ], "one_to_many"


def scenario_many_to_one():
    """{A, B} → C  (two codes merge into one)"""
    a, b, c = next_code(), next_code(), next_code()
    return [
        # Introduce A and B in separate events
        [{"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": a}],
        [{"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": b}],
        # A merges into new code C
        [
            {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": c},
            {
                "code_type_id": CODE_TYPE_ID,
                "type": "chain",
                "introduction_code": c,
                "discontinuation_code": a,
            },
            {"code_type_id": CODE_TYPE_ID, "type": "DISCONT", "discontinuation_code": a},
        ],
        # B also merges into C (C already active)
        [
            {
                "code_type_id": CODE_TYPE_ID,
                "type": "chain",
                "introduction_code": c,
                "discontinuation_code": b,
            },
            {"code_type_id": CODE_TYPE_ID, "type": "DISCONT", "discontinuation_code": b},
        ],
    ], "many_to_one"


_SCENARIOS = [
    (0.30, scenario_chain3),
    (0.20, scenario_chain4),
    (0.25, scenario_one_to_many),
    (0.25, scenario_many_to_one),
]


def pick_scenario():
    r = random.random()
    cum = 0.0
    for weight, fn in _SCENARIOS:
        cum += weight
        if r <= cum:
            return fn()
    return _SCENARIOS[-1][1]()


# ── Main family creation loop ──────────────────────────────────────
def create_families():
    print(f"\nCreating {TOTAL_FAMILIES} familys ...")
    t0 = time.time()
    api_calls = 0
    for i in range(1, TOTAL_FAMILIES + 1):
        country = COUNTRIES[(i - 1) % len(COUNTRIES)]
        event_groups, tag = pick_scenario()
        dates = rand_date_sequence(len(event_groups))
        for step, (transitions, d) in enumerate(zip(event_groups, dates), 1):
            # Add date to each transition
            for t in transitions:
                t["date"] = str(d)
            payload = {
                "iso_country_code": country,
                "comment": f"auto-{tag}-{i}-step{step}",
                "transitions_write": transitions,
            }
            r = post(f"family_{i}_{tag}_s{step}", "/api/events/", payload)
            api_calls += 1
            if r.status_code not in (200, 201):
                print(f"  WARNING family {i} ({tag}) step {step}: HTTP {r.status_code}")
        if i % 500 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed
            print(f"  {i:>6}/{TOTAL_FAMILIES}  ({rate:.1f} lc/s)")
    elapsed = time.time() - t0
    print(
        f"Lifecycles done: {TOTAL_FAMILIES} in {elapsed:.1f}s "
        f"({TOTAL_FAMILIES / elapsed:.1f} lc/s, {api_calls} API calls)\n"
    )


# ── Failure cases ─────────────────────────────────────────────────────
def run_failure_cases():
    print("--- Failure cases (should all be rejected) ---")
    country = "PL"

    # Use a separate code range so failure setup codes don't collide
    # with family codes.
    global _code_seq
    saved_seq = _code_seq
    _code_seq = 900_000_000

    def _report(label, resp):
        ok = resp.status_code >= 400
        mark = "PASS (rejected)" if ok else "FAIL (accepted!)"
        print(f"  {label:<35} HTTP {resp.status_code}  {mark}")

    # ── 1. Double introduction ────────────────────────────────────────
    code_x = next_code()
    post(
        "fail_setup_intro_x",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "INTRO",
                    "introduction_code": code_x,
                    "date": "2025-06-01",
                },
            ],
        },
    )
    r = post(
        "fail_double_intro",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "INTRO",
                    "introduction_code": code_x,
                    "date": "2025-06-15",
                },
            ],
        },
        expect_ok=False,
    )
    _report("Double introduction", r)

    # ── 1b. Overlapping generation (intro at earlier date) ────────────
    code_overlap = next_code()
    post(
        "fail_setup_intro_overlap",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "INTRO",
                    "introduction_code": code_overlap,
                    "date": "2025-06-01",
                },
            ],
        },
    )
    post(
        "fail_setup_discont_overlap",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "DISCONT",
                    "discontinuation_code": code_overlap,
                    "date": "2025-06-10",
                },
            ],
        },
    )
    r = post(
        "fail_overlap_intro",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "INTRO",
                    "introduction_code": code_overlap,
                    "date": "2025-05-01",
                },
            ],
        },
        expect_ok=False,
    )
    _report("Overlapping generation", r)

    # ── 2. Double discontinuation ─────────────────────────────────────
    code_y = next_code()
    post(
        "fail_setup_intro_y",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "INTRO",
                    "introduction_code": code_y,
                    "date": "2025-07-01",
                },
            ],
        },
    )
    post(
        "fail_setup_discont_y",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "DISCONT",
                    "discontinuation_code": code_y,
                    "date": "2025-07-15",
                },
            ],
        },
    )
    r = post(
        "fail_double_discont",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "DISCONT",
                    "discontinuation_code": code_y,
                    "date": "2025-07-20",
                },
            ],
        },
        expect_ok=False,
    )
    _report("Double discontinuation", r)

    # ── 3. chain with non-existing PO code ─────────────────────────────
    code_pi = next_code()
    code_phantom_po = next_code()  # never introduced
    post(
        "fail_setup_intro_pi",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "INTRO",
                    "introduction_code": code_pi,
                    "date": "2025-08-01",
                },
            ],
        },
    )
    r = post(
        "fail_chain_bad_po",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "chain",
                    "introduction_code": code_pi,
                    "discontinuation_code": code_phantom_po,
                    "date": "2025-08-15",
                }
            ],
        },
        expect_ok=False,
    )
    _report("chain non-existing PO code", r)

    # ── 4. chain with non-existing PI code (no proxy) ──────────────────
    code_po = next_code()
    code_phantom_pi = next_code()  # never introduced
    post(
        "fail_setup_intro_po",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "INTRO",
                    "introduction_code": code_po,
                    "date": "2025-09-01",
                },
            ],
        },
    )
    r = post(
        "fail_chain_bad_pi",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "chain",
                    "introduction_code": code_phantom_pi,
                    "discontinuation_code": code_po,
                    "date": "2025-09-15",
                }
            ],
        },
        expect_ok=False,
    )
    _report("chain non-existing PI code", r)

    # ── 5. Discontinuation on never-introduced code ───────────────────
    code_phantom = next_code()
    r = post(
        "fail_discont_phantom",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "DISCONT",
                    "discontinuation_code": code_phantom,
                    "date": "2025-10-01",
                },
            ],
        },
        expect_ok=False,
    )
    _report("Discont never-introduced code", r)

    # ── 6. chain missing discontinuation_code field ─────────────────────────────────
    r = post(
        "fail_chain_missing_po",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "chain",
                    "introduction_code": next_code(),
                    "date": "2025-11-01",
                }
            ],
        },
        expect_ok=False,
    )
    _report("chain missing discontinuation_code", r)

    # ── 7. Introduction missing introduction_code field ─────────────────────────
    r = post(
        "fail_intro_no_pi",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "date": "2025-11-15"},
            ],
        },
        expect_ok=False,
    )
    _report("Intro missing introduction_code", r)

    # ── 8. Discontinuation missing discontinuation_code field ──────────────────────
    r = post(
        "fail_discont_no_po",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {"code_type_id": CODE_TYPE_ID, "type": "DISCONT", "date": "2025-11-20"},
            ],
        },
        expect_ok=False,
    )
    _report("Discont missing discontinuation_code", r)

    # ── 9. chain where introduction_code == discontinuation_code ──────────────────────────────
    code_same = next_code()
    post(
        "fail_setup_intro_same",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "INTRO",
                    "introduction_code": code_same,
                    "date": "2025-12-01",
                },
            ],
        },
    )
    r = post(
        "fail_chain_same_codes",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "chain",
                    "introduction_code": code_same,
                    "discontinuation_code": code_same,
                    "date": "2025-12-10",
                }
            ],
        },
        expect_ok=False,
    )
    _report("chain introduction_code == discontinuation_code", r)

    # ── 10. Invalid country code ──────────────────────────────────────
    r = post(
        "fail_bad_country",
        "/api/events/",
        {
            "iso_country_code": "ZZ",
            "transitions_write": [
                {
                    "code_type_id": CODE_TYPE_ID,
                    "type": "INTRO",
                    "introduction_code": next_code(),
                    "date": "2025-12-15",
                },
            ],
        },
        expect_ok=False,
    )
    _report("Invalid country code (ZZ)", r)

    # ── 11. Invalid code_type ─────────────────────────────────────────
    r = post(
        "fail_bad_code_type",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {
                    "code_type_id": "NOPE",
                    "type": "INTRO",
                    "introduction_code": next_code(),
                    "date": "2025-12-20",
                },
            ],
        },
        expect_ok=False,
    )
    _report("Invalid code_type", r)

    # ── 12. Missing date ──────────────────────────────────────────────
    r = post(
        "fail_no_date",
        "/api/events/",
        {
            "iso_country_code": country,
            "transitions_write": [
                {"code_type_id": CODE_TYPE_ID, "type": "INTRO", "introduction_code": next_code()},
            ],
        },
        expect_ok=False,
    )
    _report("Missing date", r)

    _code_seq = saved_seq
    print()


# ── Verification spot-checks ─────────────────────────────────────────
def run_spot_checks():
    """Resolve a few codes via the API to confirm familys were built."""
    print("--- Spot-check: resolve API ---")
    # Grab a few recently created events and verify their codes resolve
    r = get("spot_list_events", "/api/events/", {"page_size": 5})
    if r.status_code != 200:
        print("  Could not list events, skipping spot-checks.")
        return
    events = r.json().get("results", r.json()) if isinstance(r.json(), dict) else r.json()
    checked = 0
    for ev in events[:5]:
        for tr in ev.get("transitions", []):
            intro = tr.get("introduction")
            if intro and intro.get("introduction_code"):
                code = intro["introduction_code"]
                ct_id = tr["code_type_id"]
                country = ev["iso_country_code"]
                tr_date = tr["date"]
                rr = get(
                    f"spot_resolve_{code}",
                    "/api/resolve/",
                    {
                        "code": code,
                        "code_type": ct_id,
                        "country": country,
                        "date": tr_date,
                    },
                )
                status_str = "OK" if rr.status_code == 200 else f"HTTP {rr.status_code}"
                print(f"  code={code} country={country} date={tr_date} → {status_str}")
                checked += 1
                if checked >= 5:
                    break
        if checked >= 5:
            break
    if checked == 0:
        print("  No introductions found to spot-check.")
    print()


# ── Entry point ───────────────────────────────────────────────────────
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="chain API stress test — creates familys and runs failure cases.",
    )
    p.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of the chain server (default: {DEFAULT_BASE_URL})",
    )
    p.add_argument(
        "--log-path",
        default=DEFAULT_LOG_PATH,
        help=f"Path for the JSONL output log (default: {DEFAULT_LOG_PATH})",
    )
    p.add_argument(
        "--total",
        type=int,
        default=DEFAULT_TOTAL,
        help=f"Number of familys to create (default: {DEFAULT_TOTAL})",
    )
    p.add_argument(
        "--countries",
        nargs="+",
        default=DEFAULT_COUNTRIES,
        help=f"ISO country codes to use (default: {' '.join(DEFAULT_COUNTRIES)})",
    )
    p.add_argument(
        "--code-type-id",
        default=DEFAULT_CODE_TYPE_ID,
        help=f"Code type ID to use (default: {DEFAULT_CODE_TYPE_ID})",
    )
    p.add_argument(
        "--delete-events",
        action="store_true",
        help="Delete all events via the API before running",
    )
    return p.parse_args(argv)


def main():
    global BASE_URL, LOG_PATH, TOTAL_FAMILIES, COUNTRIES, CODE_TYPE_ID, _log_fh

    args = parse_args()
    BASE_URL = args.base_url
    LOG_PATH = Path(args.log_path)
    TOTAL_FAMILIES = args.total
    COUNTRIES = [c.upper() for c in args.countries]
    CODE_TYPE_ID = args.code_type_id

    print(f"chain API Test — target: {BASE_URL}")
    print(f"Log file: {LOG_PATH.resolve()}")
    print(f"Lifecycles: {TOTAL_FAMILIES}  Countries: {COUNTRIES}  CodeType: {CODE_TYPE_ID}\n")

    _log_fh = LOG_PATH.open("w", encoding="utf-8")
    try:
        setup()
        if args.delete_events:
            delete_all_events()
        create_families()
        run_failure_cases()
        run_spot_checks()

        print("=== Summary ===")
        print(f"  Successful API calls:     {stats['success']}")
        print(f"  Expected failures:        {stats['expected_fail']}")
        print(f"  Unexpected failures:      {stats['unexpected_fail']}")
        print(f"  Log: {LOG_PATH.resolve()}")
    finally:
        _log_fh.close()


if __name__ == "__main__":
    main()
