#!/usr/bin/env python3
"""One-off polish: fill in missing `level` properties so the saved
System/Subsystem/Component views in Crux Lite show complete green.

A test case without `level` is dropped from a level-filtered view's
participating set; a requirement whose ONLY test cases are dropped reads
UNCOVERED there (view artifact, not missing evidence). Same doc-write rules
as crux_seed.py: run off-demo, close app tabs first.

Usage: python3 crux_polish.py --apply   (dry run without --apply)
"""

from __future__ import annotations

import argparse
import datetime
import uuid

from crux_kv import load_doc, save_doc
from staging_env import ACTOR_ID, ACTOR_NAME

LEVEL_FIXES = {
    # test cases
    "ENG-TC-001": "Component",
    "SAT-TC-002": "Component",
    "FCC-TC-004": "Component",
    "GEN-TC-001": "Component",
    "NAV-TC-006": "Subsystem",
    "PRP-TC-003": "Subsystem",
    "DL-TC-004": "Subsystem",
    # requirements
    "DAA-REQ-001": "Component",
}


def now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    manifest_entry, doc = load_doc()
    changed = []
    for obj in doc["objects"]:
        if obj.get("archived"):
            continue
        props = obj.get("properties") or {}
        ext = props.get("external_id")
        want = LEVEL_FIXES.get(ext)
        if want is None or props.get("level") == want:
            continue
        before = props.get("level")
        props["level"] = want
        obj["properties"] = props
        obj["updatedAt"] = now_iso()
        obj["updatedBy"] = ACTOR_ID
        seqs = [e["seq"] for e in doc["changelog"] if e["objectId"] == obj["id"]]
        doc["changelog"].append(
            {
                "id": str(uuid.uuid4()),
                "objectId": obj["id"],
                "seq": (max(seqs) + 1) if seqs else 1,
                "at": now_iso(),
                "actorId": ACTOR_ID,
                "actorName": ACTOR_NAME,
                "action": "update",
                "source": "manual",
                "deltas": [{"key": "level", "before": before, "after": want}],
            }
        )
        changed.append(f"{ext}: level {before!r} → {want!r}")

    print("\n".join(changed) or "nothing to change")
    if not args.apply or not changed:
        if changed:
            print("\ndry run — re-run with --apply")
        return
    revision = save_doc(manifest_entry, doc)
    print(f"saved, revision {revision}")


if __name__ == "__main__":
    main()
