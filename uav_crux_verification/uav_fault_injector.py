#!/usr/bin/env python3
"""Arm/clear the failure track for the verification campaign.

Arming does nothing until the orchestrator commands the armed requirement's
scenario — then the streamer drives the requirement's first trigger channel
past its threshold for the middle third of the window, the checklist
execution resolves with violations, and the procedure fails out.

Usage:
    python3 uav_fault_injector.py arm [--requirement PWR-REQ-001]
    python3 uav_fault_injector.py clear
    python3 uav_fault_injector.py status
"""

from __future__ import annotations

import argparse
import json

from command_file import locked_update, read_state
from uav_limits import FAULT_REQUIREMENT, REQUIREMENT_TRIGGERS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["arm", "clear", "status"])
    parser.add_argument("--requirement", default=FAULT_REQUIREMENT)
    args = parser.parse_args()

    if args.action == "status":
        print(json.dumps(read_state().get("fault", {"armed": False}), indent=2))
        return
    if args.action == "arm":
        if args.requirement not in REQUIREMENT_TRIGGERS:
            raise SystemExit(f"unknown requirement {args.requirement}")
        locked_update(
            lambda s: s.update(fault={"armed": True, "requirement": args.requirement})
        )
        print(f"armed: {args.requirement} will fail its next scenario")
    else:
        locked_update(lambda s: s.update(fault={"armed": False, "requirement": None}))
        print("cleared")


if __name__ == "__main__":
    main()
