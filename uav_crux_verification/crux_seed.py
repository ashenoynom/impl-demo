#!/usr/bin/env python3
"""Seed the Crux Lite "UAV Demo" project for the automated verification demo.

One doc write (see crux_kv.py's WRITE WARNING) that:

1. Upserts a RequirementCheck (violation triggers from uav_limits.py) onto
   every live requirement in REQUIREMENT_TRIGGERS — replacing the three toy
   drafts that were there.
2. Authors minimal test cases for the two requirements that had none
   (PAY-REQ-002 → PAY-TC-004, DAA-REQ-001 → DAA-TC-001): without a `verifies`
   test case a requirement can never leave "uncovered".
3. Archives the empty stub REQ-10 (reversible in the UI) so the catalog can
   read all-green.
4. Adds runExclusion rows for every in-scope legacy run (crux_project=UAV)
   that is not one of ours — legacy runs have no data reviews, which pins
   their test cases at "pending" forever. Our runs are recognized by the
   `verification_campaign` property and never excluded, so re-running the
   seed after demo runs exist stays safe.

Usage:
    python3 crux_seed.py            # dry run: print what would change
    python3 crux_seed.py --apply    # write the doc (close Crux tabs first!)
"""

from __future__ import annotations

import argparse
import datetime
import json
import urllib.request
import uuid

from crux_kv import load_doc, save_doc
from staging_env import (
    ACTOR_ID,
    ACTOR_NAME,
    API_BASE,
    CRUX_PROJECT_PROPERTY,
    CRUX_PROJECT_VALUE,
    WORKSPACE_RID,
    token,
)
from uav_limits import REQUIREMENT_TRIGGERS, check_tree

CAMPAIGN_PROPERTY = "verification_campaign"

NEW_TEST_CASES = [
    {
        "requirement_ext": "PAY-REQ-002",
        "external_id": "PAY-TC-004",
        "title": "nominal conditions",
        "description": (
            "Subsystem-level test of the EO/IR payload. Runs the standard "
            "target-detection scenario and scores detection range against the "
            "requirement check (eoir_detect_km >= 3 km)."
        ),
        "level": "Subsystem",
    },
    {
        "requirement_ext": "DAA-REQ-001",
        "external_id": "DAA-TC-001",
        "title": "nominal conditions",
        "description": (
            "Component-level test of the DAA radar. Runs the encounter scenario "
            "and scores the false-alarm rate against the requirement check "
            "(false_alarm_per_hr <= 1/h)."
        ),
        "level": "Component",
    },
]

ARCHIVE_STUBS = ["REQ-10"]


def now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def fetch_in_scope_runs() -> list[dict]:
    """All non-archived workspace runs carrying crux_project=UAV."""
    runs: list[dict] = []
    page_token = ""
    while True:
        body = {
            "sort": {"isDescending": True, "field": "START_TIME"},
            "query": {"type": "workspace", "workspace": WORKSPACE_RID},
            "pageSize": 500,
            **({"nextPageToken": page_token} if page_token else {}),
        }
        req = urllib.request.Request(
            f"{API_BASE}/scout/v1/search-runs",
            method="POST",
            headers={"Authorization": f"Bearer {token()}", "content-type": "application/json"},
            data=json.dumps(body).encode(),
        )
        with urllib.request.urlopen(req) as resp:
            page = json.loads(resp.read())
        for run in page.get("results", []):
            props = run.get("properties") or {}
            if props.get(CRUX_PROJECT_PROPERTY) == CRUX_PROJECT_VALUE:
                runs.append(run)
        page_token = page.get("nextPageToken") or ""
        if not page_token:
            break
    return runs


def next_seq(doc: dict, object_id: str) -> int:
    seqs = [e["seq"] for e in doc["changelog"] if e["objectId"] == object_id]
    return (max(seqs) + 1) if seqs else 1


def changelog_entry(object_id: str, seq: int, action: str, deltas: list) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "objectId": object_id,
        "seq": seq,
        "at": now_iso(),
        "actorId": ACTOR_ID,
        "actorName": ACTOR_NAME,
        "action": action,
        "source": "manual",
        "deltas": deltas,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the doc (default: dry run)")
    args = parser.parse_args()

    manifest_entry, doc = load_doc()
    live = {
        (o.get("properties") or {}).get("external_id"): o
        for o in doc["objects"]
        if not o.get("archived")
    }
    report: list[str] = []

    # 1. Upsert checks.
    checks_by_req = {c["requirementId"]: c for c in doc["checks"]}
    upserted = 0
    for ext_id in REQUIREMENT_TRIGGERS:
        obj = live.get(ext_id)
        if obj is None or obj["typeId"] != "builtin-requirement":
            report.append(f"  !! no live requirement {ext_id}; skipping its check")
            continue
        checks_by_req[obj["id"]] = {
            "requirementId": obj["id"],
            "tree": check_tree(ext_id),
            "passCriterion": "no_violations",
            "publish": {"state": "draft", "checklistRid": None, "publishedAt": None},
            "updatedBy": ACTOR_ID,
            "updatedAt": now_iso(),
        }
        upserted += 1
    # Drop checks on requirements outside the demo set (the toy drafts, and
    # anything archived).
    live_demo_ids = {
        live[e]["id"] for e in REQUIREMENT_TRIGGERS if e in live
    }
    dropped = [c for c in doc["checks"] if c["requirementId"] not in live_demo_ids]
    doc["checks"] = [c for c in checks_by_req.values() if c["requirementId"] in live_demo_ids]
    report.append(f"  checks: upserted {upserted}, dropped {len(dropped)} stale/toy")

    # 2. Missing test cases + verifies links.
    for spec in NEW_TEST_CASES:
        if spec["external_id"] in live:
            report.append(f"  test case {spec['external_id']} already exists")
            continue
        req_obj = live.get(spec["requirement_ext"])
        if req_obj is None:
            report.append(f"  !! requirement {spec['requirement_ext']} missing; cannot add TC")
            continue
        tc_id = str(uuid.uuid4())
        stamp = now_iso()
        properties = {
            "external_id": spec["external_id"],
            "title": spec["title"],
            "description": spec["description"],
            "level": spec["level"],
            "execution_mode": "Automated",
        }
        doc["objects"].append(
            {
                "id": tc_id,
                "typeId": "builtin-test-case",
                "folderId": None,
                "properties": properties,
                "reviewStatus": "draft",
                "contentAuthorId": ACTOR_ID,
                "archived": False,
                "createdAt": stamp,
                "createdBy": ACTOR_ID,
                "updatedAt": stamp,
                "updatedBy": ACTOR_ID,
            }
        )
        doc["changelog"].append(
            changelog_entry(
                tc_id,
                1,
                "create",
                [{"key": k, "before": None, "after": v} for k, v in properties.items()],
            )
        )
        doc["links"].append(
            {
                "id": str(uuid.uuid4()),
                "linkType": "verifies",
                "sourceId": tc_id,
                "targetId": req_obj["id"],
                "createdAt": stamp,
                "createdBy": ACTOR_ID,
            }
        )
        report.append(
            f"  + test case {spec['external_id']} verifies {spec['requirement_ext']}"
        )

    # 3. Archive stubs.
    for ext_id in ARCHIVE_STUBS:
        obj = live.get(ext_id)
        if obj is None:
            report.append(f"  stub {ext_id} already gone/archived")
            continue
        obj["archived"] = True
        obj["updatedAt"] = now_iso()
        obj["updatedBy"] = ACTOR_ID
        doc["changelog"].append(
            changelog_entry(obj["id"], next_seq(doc, obj["id"]), "archive", [])
        )
        report.append(f"  archived stub {ext_id}")

    # 4. Exclude legacy in-scope runs.
    excluded_ids = {row["runId"] for row in doc["runExclusions"]}
    in_scope = fetch_in_scope_runs()
    added = 0
    for run in in_scope:
        props = run.get("properties") or {}
        if props.get(CAMPAIGN_PROPERTY):
            continue  # one of ours — never exclude
        if run["rid"] in excluded_ids:
            continue
        doc["runExclusions"].append(
            {
                "runId": run["rid"],
                "actorId": ACTOR_ID,
                "actorName": ACTOR_NAME,
                "at": now_iso(),
                "note": "Legacy sim batch (no data reviews) — excluded by verification demo seed.",
            }
        )
        added += 1
    report.append(
        f"  run exclusions: {added} added ({len(in_scope)} in-scope runs swept, "
        f"{len(excluded_ids)} already excluded)"
    )

    print("Seed plan:" if not args.apply else "Applying seed:")
    print("\n".join(report))
    if not args.apply:
        print("\nDry run — re-run with --apply to write. Close any open Crux Lite tabs first.")
        return
    revision = save_doc(manifest_entry, doc)
    print(f"\nDoc saved, revision {revision}")


if __name__ == "__main__":
    main()
