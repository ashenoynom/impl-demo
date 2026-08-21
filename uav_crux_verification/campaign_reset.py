#!/usr/bin/env python3
"""Reset campaign state between rehearsals/demos.

Archives campaign runs (property verification_campaign=rtx-uav) so the next
green run starts from a clean slate — a failing run from a failure-track
rehearsal would otherwise pin its test case at "failing" in Crux forever.
Also clears leftover scenario/ack entries in the command file and the fault.

Usage:
    python3 campaign_reset.py --list
    python3 campaign_reset.py --campaign 20260821-1412   # one campaign's runs
    python3 campaign_reset.py --all                      # every campaign run
"""

from __future__ import annotations

import argparse

from nominal.core import NominalClient

from command_file import locked_update
from staging_env import PROFILE

CAMPAIGN_PROPERTY = "verification_campaign"
CAMPAIGN_VALUE = "rtx-uav"


def campaign_runs(client: NominalClient):
    return [
        run
        for run in client.search_runs(properties={CAMPAIGN_PROPERTY: CAMPAIGN_VALUE})
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--campaign", help="archive runs with this campaign_run stamp")
    parser.add_argument("--all", action="store_true", help="archive every campaign run")
    args = parser.parse_args()

    client = NominalClient.from_profile(PROFILE)
    runs = campaign_runs(client)
    print(f"{len(runs)} campaign runs found")
    for run in runs:
        stamp = (run.properties or {}).get("campaign_run", "?")
        print(f"  {run.rid}  [{stamp}]  {run.name}")

    if args.list or not (args.campaign or args.all):
        return

    doomed = [
        run
        for run in runs
        if args.all or (run.properties or {}).get("campaign_run") == args.campaign
    ]
    for run in doomed:
        run.archive()
        print(f"archived {run.rid}")

    def clear(state: dict) -> None:
        state["scenarios"] = {}
        state["acks"] = {}
        state["fault"] = {"armed": False, "requirement": None}

    locked_update(clear)
    print(f"\n{len(doomed)} runs archived; command file cleared.")


if __name__ == "__main__":
    main()
