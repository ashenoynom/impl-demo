#!/usr/bin/env python3
"""Arm live (streaming) checklist execution on GOCE assets.

Streaming execution evaluates the bus-health checklist continuously
against the asset's live stream and generates Events on violation
(auto_create_events=True; the streamingChecklistEventGenerationToggle
flag is enabled in production as of 2026-08-12). This is the third
event source in the demo, alongside manual/injector alert events and
procedure completion-action events:

    arm the fault -> checklist violations land as events on GOCE-7's
    timeline in near-real-time, before anyone executes anything.

Usage:
    python goce_streaming_checks.py start [--satellites 7]      # default GOCE-7
    python goce_streaming_checks.py start --satellites 1,7      # ref + fault sat
    python goce_streaming_checks.py stop  [--satellites 7]
"""

from __future__ import annotations

import argparse

from nominal.core import NominalClient

CHECKLIST_RID = "ri.scout.cerulean-staging.check-collection.25800248-86a1-49f5-8c52-d6f91f26f992"


def resolve_assets(client: NominalClient, sat_nos: list[int]):
    assets = []
    for n in sat_nos:
        name = f"GOCE-{n}"
        found = client.search_assets(search_text=name, properties={"asset_id": name})
        asset = next((a for a in found if a.name == name), None)
        if asset is None:
            raise SystemExit(f"Asset not found: {name}")
        assets.append(asset)
    return assets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    parser.add_argument("--satellites", default="7",
                        help="comma-separated satellite numbers (default: 7)")
    parser.add_argument("--profile", default="space_demo_prod")
    args = parser.parse_args()

    client = NominalClient.from_profile(args.profile)
    sat_nos = [int(s) for s in args.satellites.split(",")]
    assets = resolve_assets(client, sat_nos)
    checklist = client.get_checklist(CHECKLIST_RID)

    if args.action == "start":
        checklist.execute_streaming(
            assets=assets,
            integration_rids=[],
            auto_create_events=True,
        )
        names = ", ".join(a.name for a in assets)
        print(f"▶️  Streaming checklist armed on: {names}")
        print("    Violations now generate events on the asset timeline live.")
        print(f"    Checklist: {checklist.nominal_url}")
    else:
        checklist.stop_streaming_for_assets(assets=assets)
        print(f"⏹  Streaming checklist stopped for: {', '.join(a.name for a in assets)}")


if __name__ == "__main__":
    main()
