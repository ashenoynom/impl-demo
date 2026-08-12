#!/usr/bin/env python3
"""Arm, clear, or inspect the GOCE-7 HTR-2 runaway fault.

Writes command_state.json, which the CSV streamer and log streamer poll
every ~2 s. The Nominal procedure execution clears the fault through
goce_command_bridge.py — this CLI is the demo driver's manual control.

Usage:
    python goce_fault_injector.py arm            # start the heater runaway
    python goce_fault_injector.py arm --event    # ...and drop the ops alert
                                                 # event on the GOCE-7 timeline
    python goce_fault_injector.py clear    # simulate the corrective command
    python goce_fault_injector.py reset    # back to nominal instantly
    python goce_fault_injector.py status   # show state + live envelope
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from goce_limits import (
    COMMAND_NAME,
    COMMAND_STATE_PATH,
    FAULT_DELTAS,
    FAULT_RAMP_S,
    FAULT_SATELLITE,
    RECOVERY_TAU_S,
    fault_envelope,
    read_command_state,
    write_command_state,
)


def _create_alert_event(profile: str) -> None:
    """Drop the ops alert event on the GOCE-7 asset timeline (the same
    event an operator would create manually from the Fleet status grid,
    or that a live checklist violation generates)."""
    from nominal.core import NominalClient
    from nominal.core.event import EventType

    client = NominalClient.from_profile(profile)
    assets = client.search_assets(
        search_text=FAULT_SATELLITE, properties={"asset_id": FAULT_SATELLITE}
    )
    asset = next(a for a in assets if a.name == FAULT_SATELLITE)
    event = asset.create_event(
        name=f"{FAULT_SATELLITE} EPS alert — bus overcurrent / voltage sag",
        type=EventType.ERROR,
        start=datetime.now(timezone.utc),
        description=(
            "Fleet monitoring flagged rising bus current with coincident "
            "bus voltage sag and bus temperature climb on "
            f"{FAULT_SATELLITE}. Investigate via the bus health deep-dive "
            "workbook; respond per 'GOCE anomaly response: HTR-2 heater "
            "runaway (HTR2_PWR_CYCLE)'."
        ),
        labels=["GOCE", "alert", "EPS"],
        properties={"anomaly": "htr2_runaway"},
    )
    print(f"    Alert event on {FAULT_SATELLITE}: {event.rid}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["arm", "clear", "reset", "status"])
    parser.add_argument(
        "--event",
        action="store_true",
        help="arm only: also create the EPS alert event on the asset timeline",
    )
    parser.add_argument("--profile", default="space_demo_prod")
    args = parser.parse_args()

    state = read_command_state()

    if args.action == "arm":
        if state["state"] in ("armed", "active"):
            print(f"Fault already armed at t={state['t_armed']}")
            return
        now = time.time()
        write_command_state("armed", t_armed=now, source="goce_fault_injector")
        print(f"⚠️  Armed {FAULT_SATELLITE} HTR-2 runaway (ramp to full fault over {FAULT_RAMP_S:.0f}s)")
        print(f"    Affected channels: {', '.join(FAULT_DELTAS)}")
        if args.event:
            _create_alert_event(args.profile)

    elif args.action == "clear":
        if state["state"] not in ("armed", "active"):
            print(f"No active fault to clear (state: {state['state']})")
            return
        now = time.time()
        write_command_state(
            "recovering",
            t_armed=state.get("t_armed"),
            t_recovery=now,
            source="goce_fault_injector",
        )
        print(f"✅ {COMMAND_NAME} command applied — {FAULT_SATELLITE} recovering (tau {RECOVERY_TAU_S:.0f}s)")

    elif args.action == "reset":
        write_command_state("nominal", source="goce_fault_injector")
        print(f"↩️  {FAULT_SATELLITE} reset to nominal")

    else:  # status
        env = fault_envelope(state)
        print(f"Command state file: {COMMAND_STATE_PATH}")
        print(json.dumps(state, indent=2, default=str))
        print(f"Live fault envelope: {env:.3f}")
        for ch, delta in FAULT_DELTAS.items():
            print(f"  {ch}: {delta * env:+.3f}")


if __name__ == "__main__":
    main()
