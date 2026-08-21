#!/usr/bin/env python3
"""Generate one Nominal procedure per Crux requirement (gov staging) —
NATIVE-ACTIONS edition: the procedure itself owns the side effects.

Per linked test case, three steps:
  1. "Transmit scenario command" — completion actions: send_notification
     through the verification-uplink webhook (message carries the routing
     token `requirement=<ext>;tc=<ext>;window=<s>`), plus a command event.
  2. "Capture run & execute checklist" — completion actions: **create_run**
     (bounded to the scenario window, properties incl. test_case_id /
     crux_project stamped natively, run exposed as run_output_field_id) and
     **apply_checklists** (the requirement's published checklist against that
     run), plus an event. No external code creates runs or executes
     checklists.
  3. "Verify checklist outcome" — the GO/NO-GO gate. Procedures have no
     native data-review-outcome condition (SuccessCondition = timer /
     ingest_job / channel_validation / webhook only — verified 2026-08-21),
     so the orchestrator reads the data review and submits this step on
     pass or errors it on fail. Completion stamps the verified event.
Then one close-out step stamping "<REQ> VERIFIED".

Window constants: `TimestampReference(field_id=...)` does NOT resolve from
form fields server-side (int epoch and ISO text both fail with "Failed to
create run"; probed live 2026-08-21) — only constant timestamps work. So the
orchestrator commits fresh window constants per execution (build_nested's
`windows` arg) on a fixed command cadence. This file's main() creates the
procedures with placeholder windows.

Usage:
    python3 procedure_builder.py [--only SYS-REQ-004] [--recommit]
"""

from __future__ import annotations

import argparse
import json
import pathlib

from google.protobuf.timestamp_pb2 import Timestamp
from nominal.core import NominalClient
from nominal.core._utils.grpc_tools import create_grpc_channel
from nominal.protos.procedures.v1 import procedures_pb2 as p
from nominal.protos.procedures.v1.procedures_pb2_grpc import ProceduresServiceStub

from crux_kv import load_doc
from staging_env import PROFILE, WORKSPACE_RID, WORKSPACE_URL
from uav_catalog import Catalog, Requirement, load_catalog
from uav_limits import REQUIREMENT_TRIGGERS, SCENARIO_WINDOW_S

RIDS_PATH = pathlib.Path(__file__).parent / "uav_rids.json"
PLACEHOLDER_WINDOW = (1786000000, 1786000060)  # replaced per-execution


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


def procedure_title(req: Requirement) -> str:
    return f"Verify {req.external_id} — {req.title}"


def _ts(epoch_s: float) -> Timestamp:
    ts = Timestamp()
    ts.FromMilliseconds(int(epoch_s * 1000))
    return ts


def _auto_step(node_id: str, title: str, description: str, label: str, actions: list):
    return p.NestedProcedureNode(
        id=node_id,
        title=title,
        description=description,
        step=p.NestedProcedureNode.NestedStepNode(
            form=p.FormStep(
                fields=[
                    p.FormField(
                        id=f"{node_id}_ack",
                        checkbox=p.CheckboxField(label=label, is_required=False),
                    )
                ]
            ),
            is_required=True,
            completion_action_configs=actions,
        ),
    )


def _const(value: str) -> p.StringReference:
    return p.StringReference(constant=value)


def _run_property(key: str, value: str) -> p.CreateRunConfig.Property:
    return p.CreateRunConfig.Property(key=_const(key), value=_const(value))


def build_nested(
    req: Requirement,
    catalog: Catalog,
    asset_rid: str,
    integration_rid: str,
    checklist_rid: str,
    windows: dict[str, tuple[float, float]] | None = None,
    campaign_id: str = "unscheduled",
) -> p.NestedProcedure:
    """windows: test-case external id → (start_epoch_s, end_epoch_s). The
    orchestrator passes real values and commits before each execution."""
    asset_ref = p.AssetReference(rid=asset_rid)
    triggers = REQUIREMENT_TRIGGERS[req.external_id]
    trigger_text = ", ".join(f"{ch} {op} {th}" for ch, op, th in triggers)
    test_cases = sorted(
        (catalog.test_cases[tc_id] for tc_id in req.test_case_ids),
        key=lambda tc: tc.external_id,
    )

    steps: list[p.NestedProcedureNode] = []
    for tc in test_cases:
        tc_slug = _slug(tc.external_id)
        window = (windows or {}).get(tc.external_id, PLACEHOLDER_WINDOW)
        run_field = f"run_{tc_slug}"

        steps.append(
            _auto_step(
                f"cmd_{tc_slug}",
                f"Transmit scenario command — {tc.external_id}",
                f'Command the test article to run "{tc.title}" ({tc.external_id}). '
                "Submitting fires the verification-uplink webhook; the ground "
                "segment plays the scenario window on the live stream.",
                "Command authorized (automated)",
                [
                    p.CompletionActionConfig(
                        send_notification=p.SendNotificationConfig(
                            integrations=p.MultiIntegrationReference(
                                list=p.MultiIntegrationReference.IntegrationReferenceList(
                                    references=[p.IntegrationReference(rid=integration_rid)]
                                )
                            ),
                            title=_const(f"SCENARIO {tc.external_id}"),
                            message=_const(
                                f"requirement={req.external_id};tc={tc.external_id};"
                                f"window={int(SCENARIO_WINDOW_S)}"
                            ),
                        )
                    ),
                    p.CompletionActionConfig(
                        create_event=p.CreateEventConfig(
                            name=f"CMD scenario {tc.external_id} — {req.external_id}",
                            description=f'Scenario "{tc.title}" commanded via webhook uplink.',
                            labels=["verification", "command", req.external_id],
                            asset_references=[asset_ref],
                        )
                    ),
                ],
            )
        )
        steps.append(
            _auto_step(
                f"capture_{tc_slug}",
                f"Capture run — {tc.external_id}",
                f"Creates the {tc.external_id} run over the scheduled scenario "
                "window as a native procedure action (run handed to the next "
                "step via its output field).",
                "Scenario window complete (automated)",
                [
                    p.CompletionActionConfig(
                        create_run=p.CreateRunConfig(
                            run_output_field_id=run_field,
                            name=_const(f"{tc.external_id} — {req.external_id} verification"),
                            description=_const(
                                f"Automated verification of {req.external_id} via "
                                f"{tc.external_id}. Campaign {campaign_id}."
                            ),
                            assets=p.MultiAssetReference(
                                list=p.MultiAssetReference.AssetReferenceList(
                                    references=[asset_ref]
                                )
                            ),
                            time_range=p.TimeRangeReference(
                                literal=p.TimeRangeReference.RangeLiteral(
                                    start=p.TimestampReference(constant=_ts(window[0])),
                                    end=p.TimestampReference(constant=_ts(window[1])),
                                )
                            ),
                            properties=[
                                _run_property("test_case_id", tc.external_id),
                                _run_property("crux_project", "UAV"),
                                _run_property("verification_campaign", "rtx-uav"),
                                _run_property("campaign_run", campaign_id),
                                _run_property("requirement", req.external_id),
                                _run_property("source", "procedure"),
                            ],
                        )
                    ),
                    p.CompletionActionConfig(
                        create_event=p.CreateEventConfig(
                            name=f"Run captured — {tc.external_id}",
                            description=(
                                f"{tc.external_id} run created over the scenario window "
                                "by the procedure's create_run action."
                            ),
                            labels=["verification", "capture", req.external_id],
                            asset_references=[asset_ref],
                        )
                    ),
                ],
            )
        )
        # apply_checklists lives on its OWN step, and the run reference is
        # STEP-QUALIFIED: cross-step field references parse as
        # "{stepId}.{fieldId}" (scout FieldReferenceUtils) — a bare field id
        # is treated as a global field and fails with "Failed to apply
        # checklists". Same-step resolution reads form values, not action
        # outputs, so the action can never consume its own step's run.
        steps.append(
            _auto_step(
                f"score_{tc_slug}",
                f"Execute checklist — {tc.external_id}",
                f"Executes the published {req.external_id} checklist against the "
                f"captured run (violation triggers: {trigger_text}) — a native "
                "procedure action producing the data review.",
                "Checklist execution dispatched (automated)",
                [
                    p.CompletionActionConfig(
                        apply_checklists=p.ApplyChecklistsConfig(
                            checklists=p.MultiChecklistReference(
                                list=p.MultiChecklistReference.ChecklistReferenceList(
                                    references=[p.ChecklistReference(rid=checklist_rid)]
                                )
                            ),
                            runs=p.MultiRunReference(
                                list=p.MultiRunReference.RunReferenceList(
                                    references=[
                                        p.RunReference(
                                            field_id=f"capture_{tc_slug}.{run_field}"
                                        )
                                    ]
                                )
                            ),
                        )
                    ),
                    p.CompletionActionConfig(
                        create_event=p.CreateEventConfig(
                            name=f"Checklist executing — {tc.external_id}",
                            description=(
                                f"{req.external_id} checklist evaluating the "
                                f"{tc.external_id} run (data review opened)."
                            ),
                            labels=["verification", "score", req.external_id],
                            asset_references=[asset_ref],
                        )
                    ),
                ],
            )
        )
        steps.append(
            _auto_step(
                f"verify_{tc_slug}",
                f"Verify {tc.external_id} against the {req.external_id} checklist",
                "GO/NO-GO gate: submits only when the data review resolved with "
                "zero violations; a violation errors this step and fails the "
                "execution.",
                "Data review resolved with zero violations (automated)",
                [
                    p.CompletionActionConfig(
                        create_event=p.CreateEventConfig(
                            name=f"{tc.external_id} verified — {req.external_id}",
                            description=(
                                f"Checklist execution passed: no violation ranges for "
                                f"{trigger_text} over the run window."
                            ),
                            labels=["verification", "pass", req.external_id],
                            asset_references=[asset_ref],
                        )
                    )
                ],
            )
        )

    steps.append(
        _auto_step(
            f"closeout_{_slug(req.external_id)}",
            f"Close out — {req.external_id} verified",
            "All linked test cases passed their checklist executions.",
            "Requirement verified (automated)",
            [
                p.CompletionActionConfig(
                    create_event=p.CreateEventConfig(
                        name=f"{req.external_id} VERIFIED — {req.title}",
                        description=(
                            f"Every test case verifying {req.external_id} passed its "
                            "checklist execution; requirement covered."
                        ),
                        labels=["verification", "requirement-verified", req.external_id],
                        asset_references=[asset_ref],
                    )
                )
            ],
        )
    )

    section = p.NestedProcedureNode(
        id=f"verify_{_slug(req.external_id)}",
        title=f"Automated verification — {req.external_id}",
        description=(
            f"{req.title}. Level: {req.level or 'n/a'}. Violation triggers: {trigger_text}."
        ),
        steps=steps,
    )
    return p.NestedProcedure(
        title=procedure_title(req),
        description=(
            f"Automated verification procedure for {req.external_id} — {req.title}. "
            "Generated from the Crux requirements catalog; runs and checklist "
            "executions are native procedure actions. "
            f"Test cases: {', '.join(tc.external_id for tc in test_cases)}."
        ),
        steps=[section],
    )


def checklist_rids_by_requirement(doc: dict) -> dict[str, str]:
    return {
        chk["requirementId"]: chk["publish"]["checklistRid"]
        for chk in doc["checks"]
        if chk["publish"].get("checklistRid")
    }


def make_stubs(client: NominalClient) -> ProceduresServiceStub:
    b = client._clients
    channel = create_grpc_channel(
        api_base_url=b._api_base_url,
        service_config=b._service_config,
        user_agent=b._user_agent,
        auth_header=b.auth_header,
        header_provider=b.header_provider,
    )
    return ProceduresServiceStub(channel)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="one requirement external id")
    parser.add_argument("--recommit", action="store_true")
    args = parser.parse_args()

    rids = json.loads(RIDS_PATH.read_text())
    client = NominalClient.from_profile(PROFILE)
    procs = make_stubs(client)

    _, doc = load_doc()
    catalog = load_catalog(doc)
    checklists = checklist_rids_by_requirement(doc)

    existing: dict[str, str] = {}
    resp = procs.SearchProcedures(
        p.SearchProceduresRequest(query=p.ProcedureSearchQuery(search_text="Verify "), page_size=200)
    )
    for meta in resp.procedure_metadata:
        existing[meta.title] = meta.rid

    procedure_rids: dict[str, str] = dict(rids.get("procedure_rids", {}))
    for req in sorted(catalog.requirements.values(), key=lambda r: r.external_id):
        if args.only and req.external_id != args.only:
            continue
        if req.external_id not in REQUIREMENT_TRIGGERS or req.id not in checklists:
            continue
        title = procedure_title(req)
        nested = build_nested(
            req, catalog, rids["asset_rid"], rids["uplink_integration_rid"], checklists[req.id]
        )
        if title in existing and not args.recommit:
            procedure_rids[req.external_id] = existing[title]
            print(f"skip     {req.external_id}: {existing[title]}")
            continue
        parsed = procs.ParseNestedProcedure(p.ParseNestedProcedureRequest(nested_procedure=nested))
        state = parsed.procedure.state
        if title in existing:
            rid = existing[title]
            got = procs.GetProcedure(p.GetProcedureRequest(rid=rid))
            procs.Commit(
                p.CommitRequest(
                    rid=rid,
                    latest_commit_on_branch=got.procedure.commit,
                    message="Regenerated: native create_run + apply_checklists",
                    state=state,
                )
            )
            print(f"recommit {req.external_id}: {rid}")
        else:
            created = procs.CreateProcedure(
                p.CreateProcedureRequest(
                    title=title,
                    description=nested.description,
                    state=state,
                    workspace=WORKSPACE_RID,
                    commit_message="Generated from Crux catalog (native actions)",
                    is_published=True,
                )
            )
            rid = created.procedure.rid
            print(f"created  {req.external_id}: {rid}")
        procedure_rids[req.external_id] = rid

    rids["procedure_rids"] = procedure_rids
    RIDS_PATH.write_text(json.dumps(rids, indent=2))
    print(f"\n{len(procedure_rids)} procedure rids recorded")
    if procedure_rids:
        sample = next(iter(procedure_rids.values()))
        print(f"sample: {WORKSPACE_URL}/procedures/template/{sample}")


if __name__ == "__main__":
    main()
