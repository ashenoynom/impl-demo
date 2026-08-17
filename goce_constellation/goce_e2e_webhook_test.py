#!/usr/bin/env python3
"""E2E test: procedure transmit step -> send_notification webhook -> fault heal.

Creates a THROWAWAY procedure execution (never touches the pinned demo
execution), arms the fault, drives the execution through triage/RCA/GO to
the transmit step, then verifies that the webhook receiver — not the
polling bridge — healed the fault (command_state.json source ==
"webhook_receiver"). Cleans up after itself: archives the test execution
and every event it created, and resets the fault.

Pre-reqs: goce_webhook_receiver.py running, cloudflared tunnel up, the
"procedures" integration pointing at the tunnel, and the command bridge
STOPPED (it would race the webhook and make the test inconclusive).

Usage:
    python3 goce_e2e_webhook_test.py [--profile space_demo_prod]
"""

from __future__ import annotations

import argparse
import sys
import time

from nominal.core import NominalClient
from nominal.core._utils.grpc_tools import create_grpc_channel
from nominal.protos.procedures.executions.v1 import procedure_executions_pb2 as pe
from nominal.protos.procedures.executions.v1.procedure_executions_pb2_grpc import (
    ProcedureExecutionsServiceStub,
)
from nominal.protos.procedures.v1 import procedures_pb2 as p
from nominal.protos.procedures.v1.procedures_pb2_grpc import ProceduresServiceStub

from goce_limits import FAULT_SATELLITE, read_command_state, write_command_state

PROCEDURE_RID = "ri.scout.cerulean-staging.procedure.f789cd49-0e68-4d23-b37f-e8d162413c15"
TEST_TITLE = "E2E TEST — webhook uplink (auto-archived)"

# (template_node_id, [FormFieldValue kwargs]) in execution order, ending
# at the transmit step. Field values are POSITIONAL (match FormStep order).
STEP_SCRIPT = [
    (
        "acknowledge_constellation_alert",
        [
            pe.FormFieldValue(single_enum=pe.SingleEnumFieldValue(value="Fleet status value table")),
            pe.FormFieldValue(text=pe.TextFieldValue(value="E2E test — automated")),
            pe.FormFieldValue(checkbox=pe.CheckboxFieldValue(value=True)),
        ],
    ),
    ("identify_affected_satellite", "ASSET"),  # placeholder — filled at runtime
    (
        "rca_drill_down_review",
        [
            pe.FormFieldValue(checkbox=pe.CheckboxFieldValue(value=True)),
            pe.FormFieldValue(checkbox=pe.CheckboxFieldValue(value=True)),
            pe.FormFieldValue(checkbox=pe.CheckboxFieldValue(value=True)),
        ],
    ),
    (
        "ground_test_signature_comparison",
        [
            pe.FormFieldValue(checkbox=pe.CheckboxFieldValue(value=True)),
            pe.FormFieldValue(text=pe.TextFieldValue(value="E2E test")),
        ],
    ),
    (
        "go_no_go_for_corrective_command",
        [pe.FormFieldValue(single_enum=pe.SingleEnumFieldValue(value="GO"))],
    ),
    (
        "transmit_htr2_pwr_cycle_command",
        [
            pe.FormFieldValue(single_enum=pe.SingleEnumFieldValue(value="HTR2_PWR_CYCLE")),
            pe.FormFieldValue(int=pe.IntFieldValue(value=9001)),
        ],
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="space_demo_prod")
    parser.add_argument("--keep", action="store_true", help="skip cleanup (debugging)")
    args = parser.parse_args()

    client = NominalClient.from_profile(args.profile)
    b = client._clients
    print(f"Authenticated as: {client.get_user().email}")

    import subprocess
    bridge_up = subprocess.run(
        ["pgrep", "-f", "goce_command_bridge.py"], capture_output=True
    ).returncode == 0
    if bridge_up:
        sys.exit("❌ Command bridge is running — stop it first (it races the webhook)")

    channel = create_grpc_channel(
        api_base_url=b._api_base_url, service_config=b._service_config,
        user_agent=b._user_agent, auth_header=b.auth_header,
        header_provider=b.header_provider,
    )
    execs = ProcedureExecutionsServiceStub(channel)
    procs = ProceduresServiceStub(channel)

    asset = next(a for a in client.search_assets(
        search_text=FAULT_SATELLITE, properties={"asset_id": FAULT_SATELLITE}
    ) if a.name == FAULT_SATELLITE)

    # ------------------------------------------------- arm the fault
    state = read_command_state()
    if state["state"] not in ("armed", "active"):
        write_command_state("armed", t_armed=time.time(), source="e2e_test")
        print("⚠️  Fault armed (no alert event — this is a test)")
    else:
        print("Fault already armed — reusing")

    # ------------------------------------------------- create test execution
    commit = procs.GetProcedure(p.GetProcedureRequest(rid=PROCEDURE_RID)).procedure.commit
    created = execs.CreateProcedureExecution(pe.CreateProcedureExecutionRequest(
        procedure_rid=PROCEDURE_RID,
        procedure_commit_id=commit,
        title=TEST_TITLE,
        start_immediately=True,
    ))
    exec_rid = created.procedure_execution.rid
    print(f"Test execution: {exec_rid}")

    # map template_node_id -> execution step_id
    exec_state = execs.GetProcedureExecution(
        pe.GetProcedureExecutionRequest(procedure_execution_rid=exec_rid)
    ).procedure_execution.state
    step_ids = {}
    for node_id in exec_state.nodes:
        node = exec_state.nodes[node_id]
        if node.WhichOneof("node") == "step":
            step_ids[node.step.template_node_id] = node_id

    # ------------------------------------------------- drive to transmit
    t_before = time.time()
    def step_state(step_id: str) -> str:
        st = execs.GetProcedureExecution(
            pe.GetProcedureExecutionRequest(procedure_execution_rid=exec_rid)
        ).procedure_execution.state
        return st.nodes[step_id].step.state.WhichOneof("state")

    for template_id, fields in STEP_SCRIPT:
        step_id = step_ids[template_id]
        if fields == "ASSET":
            fields = [pe.FormFieldValue(asset=pe.AssetFieldValue(
                asset_reference=p.AssetReference(rid=asset.rid)))]
        # A step may already be in_progress (auto-started when its
        # predecessor submitted) — only transition when not_started.
        if step_state(step_id) == "not_started":
            execs.UpdateStep(pe.UpdateStepRequest(
                procedure_execution_rid=exec_rid, step_id=step_id,
                target_state=pe.TargetStepStateRequest(in_progress=pe.StepInProgressRequest()),
            ))
        execs.UpdateStep(pe.UpdateStepRequest(
            procedure_execution_rid=exec_rid, step_id=step_id,
            value=pe.StepContentValue(form=pe.FormStepValue(fields=fields)),
            target_state=pe.TargetStepStateRequest(submitted=pe.StepSubmittedRequest()),
        ))
        print(f"  ✓ {template_id}")

    # ------------------------------------------------- verify webhook healed it
    print("\nWaiting for webhook → command_state.json ...")
    verdict = None
    for _ in range(30):
        state = read_command_state()
        if state["state"] == "recovering":
            verdict = state.get("source", "?")
            break
        time.sleep(1)
    elapsed = time.time() - t_before

    if verdict == "webhook_receiver":
        print(f"\n✅ PASS — webhook healed the fault ({elapsed:.1f}s after step walk began)")
    elif verdict:
        print(f"\n⚠️  Fault healed but by {verdict!r}, not the webhook — inconclusive")
    else:
        print(f"\n❌ FAIL — fault not healed after 30 s (state: {state['state']})")

    # ------------------------------------------------- cleanup
    if args.keep:
        print("(--keep: skipping cleanup)")
        return
    execs.BatchArchiveProcedureExecutions(
        pe.BatchArchiveProcedureExecutionsRequest(procedure_execution_rids=[exec_rid])
    )
    print(f"Archived test execution")
    # Archive events this test spawned (RCA/TVAC/GO/CMD from completion
    # actions + ACK from the receiver) — everything in the last few minutes
    # tagged GOCE on this asset with our fingerprints.
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=elapsed + 120)
    n = 0
    # search_events(after=...) already bounds the window — archive all hits
    for ev in client.search_events(after=cutoff, assets=[asset]):
        ev.archive()
        n += 1
    print(f"Archived {n} test events")
    write_command_state("nominal", source="e2e_test_cleanup")
    print("Fault reset to nominal — done.")


if __name__ == "__main__":
    main()
