#!/usr/bin/env python3
"""Ground-segment command bridge: Nominal procedure execution -> spacecraft.

Polls the Nominal ProcedureExecutionsService for executions of the
"GOCE anomaly response" procedure. When an operator completes the
"Transmit HTR2_PWR_CYCLE command" step (state submitted/succeeded), the
bridge:

  1. writes command_state.json -> "recovering" (the CSV/log streamers
     poll it, so GOCE-7's telemetry starts healing within ~2 s),
  2. creates a SUCCESS event on the GOCE-7 asset ("CMD HTR2_PWR_CYCLE
     accepted by GOCE-7") — the spacecraft-side ACK on the timeline,
     bookending the procedure's own "transmitted" event.

Run it in a terminal next to the streamers for the live demo:

    python goce_command_bridge.py [--profile space_demo_prod] [--poll 5]
    python goce_command_bridge.py --once      # single poll pass (testing)
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from nominal.core import NominalClient
from nominal.core.event import EventType
from nominal.core._utils.grpc_tools import create_grpc_channel
from nominal.protos.procedures.executions.v1 import procedure_executions_pb2 as pe
from nominal.protos.procedures.executions.v1.procedure_executions_pb2_grpc import (
    ProcedureExecutionsServiceStub,
)

from goce_limits import (
    COMMAND_NAME,
    FAULT_SATELLITE,
    read_command_state,
    write_command_state,
)

PROCEDURE_TITLE = "GOCE anomaly response: HTR-2 heater runaway (HTR2_PWR_CYCLE)"
# Node ids in the procedure graph (slugs of the step titles —
# see goce_procedure_builder._slug).
TRANSMIT_NODE_ID = "transmit_htr2_pwr_cycle_command"
CLOSEOUT_NODE_ID = "close_out"
CHECKLIST_RID = "ri.scout.cerulean-staging.check-collection.25800248-86a1-49f5-8c52-d6f91f26f992"
RECOVERY_RUN_NAME = "GOCE-7 | HTR-2 recovery verification"


def _iter_step_nodes(state):
    """state.nodes is map<node_id, ProcedureExecutionNode>; each value is
    a section/step oneof — yield (node_id, step_node) for steps."""
    for node_id in state.nodes:
        node = state.nodes[node_id]
        if node.WhichOneof("node") == "step":
            yield node_id, node.step


def _step_done(step_node) -> bool:
    which = step_node.state.WhichOneof("state")
    return which in ("submitted", "succeeded")


class CommandBridge:
    def __init__(self, profile: str, poll_s: float):
        self.client = NominalClient.from_profile(profile)
        b = self.client._clients
        channel = create_grpc_channel(
            api_base_url=b._api_base_url,
            service_config=b._service_config,
            user_agent=b._user_agent,
            auth_header=b.auth_header,
            header_provider=b.header_provider,
        )
        self.execs = ProcedureExecutionsServiceStub(channel)
        self.poll_s = poll_s
        self.procedure_rid = self._resolve_procedure_rid()
        self.handled_exec_rids: set[str] = set()
        self.closed_out_exec_rids: set[str] = set()
        assets = self.client.search_assets(
            search_text=FAULT_SATELLITE, properties={"asset_id": FAULT_SATELLITE}
        )
        self.asset = next(a for a in assets if a.name == FAULT_SATELLITE)
        print(f"Bridge up. Procedure: {self.procedure_rid}")
        print(f"Watching step node '{TRANSMIT_NODE_ID}' | asset {self.asset.rid}")

    def _resolve_procedure_rid(self) -> str:
        from nominal.protos.procedures.v1 import procedures_pb2 as p
        from nominal.protos.procedures.v1.procedures_pb2_grpc import ProceduresServiceStub

        b = self.client._clients
        channel = create_grpc_channel(
            api_base_url=b._api_base_url,
            service_config=b._service_config,
            user_agent=b._user_agent,
            auth_header=b.auth_header,
            header_provider=b.header_provider,
        )
        proc = ProceduresServiceStub(channel)
        resp = proc.SearchProcedures(
            p.SearchProceduresRequest(
                query=p.ProcedureSearchQuery(search_text=PROCEDURE_TITLE), page_size=50
            )
        )
        for meta in resp.procedure_metadata:
            if meta.title == PROCEDURE_TITLE:
                return meta.rid
        raise SystemExit(f"Procedure not found: {PROCEDURE_TITLE!r} — run goce_procedure_builder.py")

    def poll_once(self) -> bool:
        """One poll pass. Returns True if any action was taken."""
        resp = self.execs.SearchProcedureExecutions(
            pe.SearchProcedureExecutionsRequest(
                query=pe.ProcedureExecutionSearchQuery(procedure_rid=self.procedure_rid),
                page_size=20,
            )
        )
        acted = False
        for meta in resp.procedure_executions:
            rid = meta.rid
            if getattr(meta, "is_archived", False):
                continue
            need_transmit = rid not in self.handled_exec_rids
            need_closeout = rid not in self.closed_out_exec_rids
            if not (need_transmit or need_closeout):
                continue
            execution = self.execs.GetProcedureExecution(
                pe.GetProcedureExecutionRequest(procedure_execution_rid=rid)
            )
            for _, step in _iter_step_nodes(execution.procedure_execution.state):
                if (
                    need_transmit
                    and step.template_node_id == TRANSMIT_NODE_ID
                    and _step_done(step)
                ):
                    self.handled_exec_rids.add(rid)
                    self._bridge_command(rid)
                    acted = True
                if (
                    need_closeout
                    and step.template_node_id == CLOSEOUT_NODE_ID
                    and _step_done(step)
                ):
                    self.closed_out_exec_rids.add(rid)
                    self._close_out(rid)
                    acted = True
        return acted

    def _close_out(self, execution_rid: str) -> None:
        """Procedure close-out: bound the recovery run that the telemetry
        gate created (it is open-ended) and execute the bus-health
        checklist against it — the all-green data review."""
        # Prefer the open-ended (just-created) recovery run; repeated demo
        # cycles leave older closed ones with the same name behind.
        matches = [r for r in self.client.search_runs(name_substring=RECOVERY_RUN_NAME)
                   if r.name == RECOVERY_RUN_NAME]
        open_runs = [r for r in matches if r.end is None]
        if not open_runs:
            # Nothing open: this close-out was already processed (e.g. a
            # stale execution seen after a bridge restart) — skip.
            print(f"[{datetime.now():%H:%M:%S}] close-out seen but no open recovery run — skipping")
            return
        run = open_runs[0]
        try:
            run = run.update(end=datetime.now(timezone.utc))
            print(f"[{datetime.now():%H:%M:%S}] 📋 Recovery run bounded — executing bus-health checklist")
            checklist = self.client.get_checklist(CHECKLIST_RID)
            review = checklist.execute(run).poll_for_completion()
            print(f"    Data review: {review.nominal_url}")
        except Exception as e:
            print(f"    close-out checklist failed: {e}")

    def _bridge_command(self, execution_rid: str) -> None:
        state = read_command_state()
        if state["state"] not in ("armed", "active"):
            print(
                f"[{datetime.now():%H:%M:%S}] Transmit step completed in "
                f"{execution_rid}, but no active fault (state: {state['state']}) — ignoring"
            )
            return
        now = time.time()
        write_command_state(
            "recovering",
            t_armed=state.get("t_armed"),
            t_recovery=now,
            source=f"procedure_execution:{execution_rid}",
        )
        print(f"[{datetime.now():%H:%M:%S}] ⚡ {COMMAND_NAME} bridged to {FAULT_SATELLITE} — telemetry recovering")
        try:
            event = self.asset.create_event(
                name=f"CMD {COMMAND_NAME} accepted by {FAULT_SATELLITE}",
                type=EventType.SUCCESS,
                start=datetime.now(timezone.utc),
                description=(
                    "Spacecraft ACK: heater controller power-cycled, duty "
                    "cycle returning to closed-loop control. Source "
                    f"procedure execution: {execution_rid}"
                ),
                labels=["GOCE", "command", "HTR-2", "ack"],
                properties={"command": COMMAND_NAME, "execution_rid": execution_rid},
            )
            print(f"    ACK event: {event.rid}")
        except Exception as e:
            print(f"    (ACK event creation failed: {e})")

    def run(self) -> None:
        print(f"Polling every {self.poll_s:.0f}s — Ctrl+C to stop")
        while True:
            try:
                self.poll_once()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[{datetime.now():%H:%M:%S}] poll error (will retry): {e}")
            time.sleep(self.poll_s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="space_demo_prod")
    parser.add_argument("--poll", type=float, default=5.0)
    parser.add_argument("--once", action="store_true", help="single poll pass and exit")
    args = parser.parse_args()

    bridge = CommandBridge(args.profile, args.poll)
    if args.once:
        hit = bridge.poll_once()
        print(f"Single pass done — command bridged: {hit}")
    else:
        try:
            bridge.run()
        except KeyboardInterrupt:
            print("\nBridge stopped")


if __name__ == "__main__":
    main()
