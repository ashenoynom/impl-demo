#!/usr/bin/env python3
"""Live probe: can a procedure natively (a) create a bounded run from form
field values, (b) stamp properties on it, (c) apply a checklist to it?

Builds a throwaway procedure with one step: two Int form fields
(window_start_epoch_s / window_end_epoch_s) + completion actions
create_run(time_range from those field_ids, properties incl. a probe marker)
and apply_checklists(run_output_field_id). Executes it against the last
~90 s of live UAV-1 data, then inspects the run that appears and its data
review.

Also answers the epoch-unit question empirically (seconds vs millis).
"""

from __future__ import annotations

import json
import pathlib
import time
from datetime import datetime, timezone

from nominal.core import NominalClient
from nominal.core._utils.grpc_tools import create_grpc_channel
from nominal.protos.procedures.executions.v1 import procedure_executions_pb2 as pe
from nominal.protos.procedures.executions.v1.procedure_executions_pb2_grpc import (
    ProcedureExecutionsServiceStub,
)
from nominal.protos.procedures.v1 import procedures_pb2 as p
from nominal.protos.procedures.v1.procedures_pb2_grpc import ProceduresServiceStub

from staging_env import PROFILE, WORKSPACE_RID

RIDS = json.loads((pathlib.Path(__file__).parent / "uav_rids.json").read_text())
PROBE_TITLE = "ZZ PROBE — native create_run + apply_checklists"


def main() -> None:
    client = NominalClient.from_profile(PROFILE)
    b = client._clients
    channel = create_grpc_channel(
        api_base_url=b._api_base_url, service_config=b._service_config,
        user_agent=b._user_agent, auth_header=b.auth_header,
        header_provider=b.header_provider,
    )
    procs = ProceduresServiceStub(channel)
    execs = ProcedureExecutionsServiceStub(channel)

    checklist_rid = None
    from crux_kv import load_doc
    _, doc = load_doc()
    for chk in doc["checks"]:
        if chk["publish"]["checklistRid"]:
            checklist_rid = chk["publish"]["checklistRid"]
            break

    step = p.NestedProcedureNode(
        id="probe_capture",
        title="Capture run & execute checklist (native)",
        description="probe",
        step=p.NestedProcedureNode.NestedStepNode(
            form=p.FormStep(
                fields=[
                    p.FormField(
                        id="window_start_epoch_s",
                        int=p.IntField(label="Window start (epoch s)", is_required=True),
                    ),
                    p.FormField(
                        id="window_end_epoch_s",
                        int=p.IntField(label="Window end (epoch s)", is_required=True),
                    ),
                ]
            ),
            is_required=True,
            completion_action_configs=[
                p.CompletionActionConfig(
                    create_run=p.CreateRunConfig(
                        run_output_field_id="probe_run",
                        name=p.StringReference(constant="ZZ PROBE native run"),
                        description=p.StringReference(constant="native create_run probe"),
                        assets=p.MultiAssetReference(
                            list=p.MultiAssetReference.AssetReferenceList(
                                references=[p.AssetReference(rid=RIDS["asset_rid"])]
                            )
                        ),
                        time_range=p.TimeRangeReference(
                            literal=p.TimeRangeReference.RangeLiteral(
                                start=p.TimestampReference(field_id="window_start_epoch_s"),
                                end=p.TimestampReference(field_id="window_end_epoch_s"),
                            )
                        ),
                        properties=[
                            p.CreateRunConfig.Property(
                                key=p.StringReference(constant="probe_marker"),
                                value=p.StringReference(constant="native-actions"),
                            )
                        ],
                    )
                ),
                p.CompletionActionConfig(
                    apply_checklists=p.ApplyChecklistsConfig(
                        checklists=p.MultiChecklistReference(
                            list=p.MultiChecklistReference.ChecklistReferenceList(
                                references=[p.ChecklistReference(rid=checklist_rid)]
                            )
                        ),
                        runs=p.MultiRunReference(
                            list=p.MultiRunReference.RunReferenceList(
                                references=[p.RunReference(field_id="probe_run")]
                            )
                        ),
                    )
                ),
            ],
        ),
    )
    nested = p.NestedProcedure(
        title=PROBE_TITLE,
        description="probe",
        steps=[p.NestedProcedureNode(id="probe_section", title="Probe", steps=[step])],
    )
    parsed = procs.ParseNestedProcedure(p.ParseNestedProcedureRequest(nested_procedure=nested))
    print("parse OK,", len(parsed.procedure.state.nodes), "nodes")
    created = procs.CreateProcedure(
        p.CreateProcedureRequest(
            title=PROBE_TITLE, description="probe", state=parsed.procedure.state,
            workspace=WORKSPACE_RID, commit_message="probe", is_published=False,
        )
    )
    proc_rid = created.procedure.rid
    print("procedure:", proc_rid)

    commit = procs.GetProcedure(p.GetProcedureRequest(rid=proc_rid)).procedure.commit
    exec_created = execs.CreateProcedureExecution(
        pe.CreateProcedureExecutionRequest(
            procedure_rid=proc_rid, procedure_commit_id=commit,
            title="probe exec", start_immediately=True,
        )
    )
    exec_rid = exec_created.procedure_execution.rid
    print("execution:", exec_rid)

    state = execs.GetProcedureExecution(
        pe.GetProcedureExecutionRequest(procedure_execution_rid=exec_rid)
    ).procedure_execution.state
    step_id = next(
        nid for nid in state.nodes
        if state.nodes[nid].WhichOneof("node") == "step"
    )

    end = int(time.time()) - 5
    start = end - 90
    execs.UpdateStep(pe.UpdateStepRequest(
        procedure_execution_rid=exec_rid, step_id=step_id,
        target_state=pe.TargetStepStateRequest(in_progress=pe.StepInProgressRequest()),
    ))
    execs.UpdateStep(pe.UpdateStepRequest(
        procedure_execution_rid=exec_rid, step_id=step_id,
        value=pe.StepContentValue(form=pe.FormStepValue(fields=[
            pe.FormFieldValue(int=pe.IntFieldValue(value=start)),
            pe.FormFieldValue(int=pe.IntFieldValue(value=end)),
        ])),
        target_state=pe.TargetStepStateRequest(submitted=pe.StepSubmittedRequest()),
    ))
    print(f"step submitted with window [{start}, {end}] (epoch s)")

    # watch for the run + review
    for i in range(20):
        time.sleep(3)
        runs = [r for r in client.search_runs(name_substring="ZZ PROBE native run")]
        if runs:
            run = runs[0]
            print("RUN CREATED:", run.rid)
            print("  start:", run.start, " end:", run.end)
            print("  props:", dict(run.properties or {}))
            expect_start = datetime.fromtimestamp(start, tz=timezone.utc)
            print("  expected start:", expect_start)
            reviews = list(run.search_data_reviews()) if hasattr(run, "search_data_reviews") else []
            print("  data reviews:", [rv.rid for rv in reviews])
            break
    else:
        print("NO RUN APPEARED after 60 s — check completion action status")
        st = execs.GetProcedureExecution(
            pe.GetProcedureExecutionRequest(procedure_execution_rid=exec_rid)
        ).procedure_execution.state
        node = st.nodes[step_id]
        print(node)

    print(f"\nprobe artifacts: procedure {proc_rid}, execution {exec_rid}")
    print("clean up with: ArchiveProcedures + archive run when done")


if __name__ == "__main__":
    main()
