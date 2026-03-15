#!/usr/bin/env python3
"""Quick smoke test for simplified chain logic."""

import requests

BASE = "http://localhost:8080"
s = requests.Session()

# Delete all events
while True:
    r = s.get(f"{BASE}/api/events/")
    data = r.json()
    events = data.get("results", data)
    if not events:
        break
    for ev in events:
        s.delete(f"{BASE}/api/events/{ev['id']}/")
print("All events deleted")

# Setup: ensure country and code type exist
s.get(f"{BASE}/api/countries/PL/").status_code == 404 and s.post(
    f"{BASE}/api/countries/", json={"code": "PL", "name": "PL"}
)
r = s.get(f"{BASE}/api/code-types/NTN/")
if r.status_code == 404:
    s.post(f"{BASE}/api/code-types/", json={"id": "NTN", "type": "National"})
print("Setup done")

# chain3: A -> B -> C
r = s.post(
    f"{BASE}/api/events/",
    json={
        "iso_country_code": "PL",
        "comment": "intro-A",
        "transitions_write": [
            {
                "code_type_id": "NTN",
                "type": "INTRO",
                "introduction_code": 100,
                "date": "2025-01-01",
            },
        ],
    },
)
print(f"Step1 INTRO A: {r.status_code}")

r = s.post(
    f"{BASE}/api/events/",
    json={
        "iso_country_code": "PL",
        "comment": "chain-B-A",
        "transitions_write": [
            {
                "code_type_id": "NTN",
                "type": "INTRO",
                "introduction_code": 200,
                "date": "2025-02-01",
            },
            {
                "code_type_id": "NTN",
                "type": "chain",
                "introduction_code": 200,
                "discontinuation_code": 100,
                "date": "2025-02-01",
            },
            {
                "code_type_id": "NTN",
                "type": "DISCONT",
                "discontinuation_code": 100,
                "date": "2025-02-01",
            },
        ],
    },
)
print(f"Step2 INTRO B + CHAIN B->A + DISCONT A: {r.status_code}")
if r.status_code >= 400:
    print(r.json())

r = s.post(
    f"{BASE}/api/events/",
    json={
        "iso_country_code": "PL",
        "comment": "chain-C-B",
        "transitions_write": [
            {
                "code_type_id": "NTN",
                "type": "INTRO",
                "introduction_code": 300,
                "date": "2025-03-01",
            },
            {
                "code_type_id": "NTN",
                "type": "chain",
                "introduction_code": 300,
                "discontinuation_code": 200,
                "date": "2025-03-01",
            },
            {
                "code_type_id": "NTN",
                "type": "DISCONT",
                "discontinuation_code": 200,
                "date": "2025-03-01",
            },
        ],
    },
)
print(f"Step3 INTRO C + CHAIN C->B + DISCONT B: {r.status_code}")
if r.status_code >= 400:
    print(r.json())

# Failure: double intro
r = s.post(
    f"{BASE}/api/events/",
    json={
        "iso_country_code": "PL",
        "comment": "fail-double-intro",
        "transitions_write": [
            {
                "code_type_id": "NTN",
                "type": "INTRO",
                "introduction_code": 300,
                "date": "2025-04-01",
            },
        ],
    },
)
print(f"Double intro (should fail): {r.status_code} {'PASS' if r.status_code >= 400 else 'FAIL'}")

# Failure: chain pi==po
r = s.post(
    f"{BASE}/api/events/",
    json={
        "iso_country_code": "PL",
        "comment": "fail-same-codes",
        "transitions_write": [
            {
                "code_type_id": "NTN",
                "type": "chain",
                "introduction_code": 300,
                "discontinuation_code": 300,
                "date": "2025-04-01",
            },
        ],
    },
)
print(f"Chain pi==po (should fail): {r.status_code} {'PASS' if r.status_code >= 400 else 'FAIL'}")

# Failure: discont non-existing
r = s.post(
    f"{BASE}/api/events/",
    json={
        "iso_country_code": "PL",
        "comment": "fail-discont-phantom",
        "transitions_write": [
            {
                "code_type_id": "NTN",
                "type": "DISCONT",
                "discontinuation_code": 999,
                "date": "2025-05-01",
            },
        ],
    },
)
print(
    f"Discont phantom (should fail): {r.status_code} {'PASS' if r.status_code >= 400 else 'FAIL'}"
)

# Failure: chain with non-existing PO code
r = s.post(
    f"{BASE}/api/events/",
    json={
        "iso_country_code": "PL",
        "comment": "fail-chain-bad-po",
        "transitions_write": [
            {
                "code_type_id": "NTN",
                "type": "chain",
                "introduction_code": 300,
                "discontinuation_code": 9999,
                "date": "2025-05-01",
            },
        ],
    },
)
print(f"Chain bad PO (should fail): {r.status_code} {'PASS' if r.status_code >= 400 else 'FAIL'}")

# Failure: chain with non-existing PI code
r = s.post(
    f"{BASE}/api/events/",
    json={
        "iso_country_code": "PL",
        "comment": "fail-chain-bad-pi",
        "transitions_write": [
            {
                "code_type_id": "NTN",
                "type": "chain",
                "introduction_code": 8888,
                "discontinuation_code": 300,
                "date": "2025-05-01",
            },
        ],
    },
)
print(f"Chain bad PI (should fail): {r.status_code} {'PASS' if r.status_code >= 400 else 'FAIL'}")

print("Done!")
