#!/usr/bin/env python3
"""Build the GOCE anomaly-response procedure in Nominal (gRPC/proto).

"GOCE anomaly response: HTR-2 heater runaway (HTR2_PWR_CYCLE)" — the
corrective-commanding leg of the demo:

  1. Anomaly triage        acknowledge the fleet alert, bind the satellite
  2. Root cause            RCA workbook review, TVAC comparison, GO/NO-GO
  3. Corrective commanding transmit HTR2_PWR_CYCLE (watched by
                           goce_command_bridge.py; completion also drops a
                           command event on the timeline)
  4. Recovery verification timed soak, channel-validation gate that only
                           passes when bus current is back in limits, then
                           close-out actions: recovery run + checklist
                           execution + recovery event

Authored as a NestedProcedure, validated server-side via
ParseNestedProcedure, then CreateProcedure (or a working-state commit if
the procedure already exists).

Usage:
    python goce_procedure_builder.py [--profile space_demo_prod]
"""

from __future__ import annotations

import argparse
import uuid

from nominal.core import NominalClient
from nominal.core._utils.grpc_tools import create_grpc_channel
from nominal.protos.procedures.v1 import procedures_pb2 as p
from nominal.protos.procedures.v1.procedures_pb2_grpc import ProceduresServiceStub

from goce_channels import BUS_CURRENT, HTR_CHANNEL
from goce_limits import (
    COMMAND_NAME,
    FAULT_SATELLITE,
    LIMIT_BUS_CURRENT_WARN_A,
    LIMIT_HTR_DUTY_LATCHED_PCT,
)

PROCEDURE_TITLE = "GOCE anomaly response: HTR-2 heater runaway (HTR2_PWR_CYCLE)"
TRANSMIT_STEP_TITLE = f"Transmit {COMMAND_NAME} command"
WORKSPACE_URL = "https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e"
COMPARE_WB_URL = f"{WORKSPACE_URL}/workbooks/ri.scout.cerulean-staging.notebook.79d27e88-dacc-4380-bfd1-497577ebb8c4"
DEEPDIVE_WB_URL = f"{WORKSPACE_URL}/workbooks/ri.scout.cerulean-staging.notebook.8013b267-e951-4aaa-8059-b842a367287f"
CHECKLIST_RID = "ri.scout.cerulean-staging.check-collection.25800248-86a1-49f5-8c52-d6f91f26f992"
# "procedures" simple-webhook integration — the transmit step fires a
# send_notification through it; goce_webhook_receiver.py (exposed via
# ngrok) receives the POST and heals the live fault.
WEBHOOK_INTEGRATION_RID = "ri.scout.cerulean-staging.integration.d142937d-63de-4998-b1fa-f8744a3528fd"
RECOVERY_RUN_NAME = "GOCE-7 | HTR-2 recovery verification"
DATA_REF = "data"


def _slug(title: str) -> str:
    """Node ids must be 'valid step identifiers' — UUIDs with hyphens are
    rejected; lowercase_underscore slugs pass."""
    return "".join(c if c.isalnum() else "_" for c in title.lower()).strip("_")


def _step(
    title: str,
    description: str,
    step: p.NestedProcedureNode.NestedStepNode,
) -> p.NestedProcedureNode:
    return p.NestedProcedureNode(
        id=_slug(title), title=title, description=description, step=step
    )


def _section(title: str, description: str, steps: list) -> p.NestedProcedureNode:
    return p.NestedProcedureNode(
        id=_slug(title), title=title, description=description, steps=steps
    )


def _form(fields: list, **kwargs) -> p.NestedProcedureNode.NestedStepNode:
    return p.NestedProcedureNode.NestedStepNode(form=p.FormStep(fields=fields), **kwargs)


def build_nested(asset_rid: str) -> p.NestedProcedure:
    goce7 = p.AssetReference(rid=asset_rid)

    # ---------------------------------------------------- 1. triage
    triage = _section(
        "Anomaly triage",
        "Acknowledge the constellation alert and bind the affected satellite.",
        [
            _step(
                "Acknowledge constellation alert",
                "Confirm the red row in the constellation workbook's Fleet "
                "status grid (or the checklist/event that paged you) and "
                "capture the initial read.",
                _form(
                    [
                        p.FormField(
                            id="alert_source",
                            label="Alert source",
                            single_enum=p.SingleEnumField(
                                label="Alert source",
                                options=[
                                    "Fleet status value table",
                                    "Bus health checklist event",
                                    "Timeline event",
                                ],
                                buttons=p.EnumFieldButtonsInputType(),
                                is_required=True,
                            ),
                        ),
                        p.FormField(
                            id="anomaly_summary",
                            label="Anomaly summary",
                            text=p.TextField(
                                label="Anomaly summary",
                                markdown=p.TextFieldMarkdownInputType(),
                            ),
                        ),
                        p.FormField(
                            id="fleet_red_confirmed",
                            checkbox=p.CheckboxField(
                                label="GOCE-7 row red in Fleet status grid "
                                "(bus I / bus V / bus temp / HTR-2 duty)",
                                is_required=True,
                            ),
                        ),
                    ],
                    is_required=True,
                ),
            ),
            _step(
                "Identify affected satellite",
                "Bind the satellite under investigation — downstream events "
                "and the recovery run attach to this asset.",
                _form(
                    [
                        p.FormField(
                            id="affected_satellite",
                            asset=p.AssetField(label="Affected satellite", is_required=True),
                        )
                    ],
                    is_required=True,
                ),
            ),
        ],
    )

    # ------------------------------------------- 2. root cause verification
    rca = _section(
        "Root cause verification",
        "Work the RCA in the bus-health deep-dive workbook, confirm the "
        "signature against the TVAC ground test, then gate on GO/NO-GO.",
        [
            _step(
                "RCA drill-down review",
                "In [GOCE-7: bus health deep-dive → EPS anomaly (RCA)]"
                f"({DEEPDIVE_WB_URL}): build the bus-power UDF (V × I) and "
                "the Stefan–Boltzmann radiator-equilibrium check from "
                "first principles.",
                _form(
                    [
                        p.FormField(
                            id="duty_latched",
                            checkbox=p.CheckboxField(
                                label=f"{HTR_CHANNEL} pinned at 100% "
                                f"(> {LIMIT_HTR_DUTY_LATCHED_PCT:.0f}% sustained)",
                                is_required=True,
                            ),
                        ),
                        p.FormField(
                            id="power_excess",
                            checkbox=p.CheckboxField(
                                label="Bus power UDF shows ~3 W excess — "
                                "HTR-2's rated draw",
                                is_required=True,
                            ),
                        ),
                        p.FormField(
                            id="radiator_deficit",
                            checkbox=p.CheckboxField(
                                label="Stefan–Boltzmann check: radiator cannot "
                                "reject fault-level power (predicted "
                                "equilibrium ≫ measured)",
                                is_required=True,
                            ),
                        ),
                    ],
                    completion_action_configs=[
                        p.CompletionActionConfig(
                            create_event=p.CreateEventConfig(
                                name=f"Root cause confirmed: HTR-2 controller latch-up — {FAULT_SATELLITE}",
                                description="RCA drill-down complete: duty "
                                "pinned at 100%, ~3 W excess bus power, "
                                "radiator cannot reject fault-level load.",
                                labels=["GOCE", "rca", "HTR-2"],
                                asset_references=[goce7],
                            )
                        )
                    ],
                ),
            ),
            _step(
                "Ground-test signature comparison",
                "Open [GOCE-7 anomaly: flight vs TVAC ground test]"
                f"({COMPARE_WB_URL}) and overlay the flight anomaly against "
                "the 2026-03 TVAC latch-up replication.",
                _form(
                    [
                        p.FormField(
                            id="tvac_match",
                            checkbox=p.CheckboxField(
                                label="Flight signature matches TVAC latch-up "
                                "(duty 100%, +1.0 A, −0.25 V, power plateau)",
                                is_required=True,
                            ),
                        ),
                        p.FormField(
                            id="evidence_notes",
                            label="Evidence notes",
                            text=p.TextField(
                                label="Evidence notes",
                                markdown=p.TextFieldMarkdownInputType(),
                            ),
                        ),
                    ],
                    completion_action_configs=[
                        p.CompletionActionConfig(
                            create_event=p.CreateEventConfig(
                                name=f"Failure signature matched to TVAC ground test — {FAULT_SATELLITE}",
                                description="Flight anomaly overlays the "
                                "2026-03 FM TVAC latch-up replication: known "
                                "failure mode with rehearsed corrective action.",
                                labels=["GOCE", "rca", "TVAC"],
                                asset_references=[goce7],
                            )
                        )
                    ],
                ),
            ),
            _step(
                "GO/NO-GO for corrective command",
                "Flight director decision to transmit HTR2_PWR_CYCLE. "
                "The decision is recorded as a timeline event on GOCE-7.",
                _form(
                    [
                        p.FormField(
                            id="go_nogo",
                            single_enum=p.SingleEnumField(
                                label="Decision",
                                options=["GO", "NO-GO"],
                                buttons=p.EnumFieldButtonsInputType(),
                                is_required=True,
                            ),
                        )
                    ],
                    is_required=True,
                    completion_action_configs=[
                        p.CompletionActionConfig(
                            create_event=p.CreateEventConfig(
                                name=f"GO decision — {COMMAND_NAME} authorized for {FAULT_SATELLITE}",
                                description="Flight director GO for corrective "
                                "commanding per anomaly response procedure.",
                                labels=["GOCE", "decision", "HTR-2"],
                                asset_references=[goce7],
                            )
                        )
                    ],
                ),
            ),
        ],
    )

    # ------------------------------------------------ 3. corrective command
    commanding = _section(
        "Corrective commanding",
        "Transmit the corrective command on the next pass. Completing the "
        "transmit step is the uplink: the ground segment bridge picks it up "
        "and radiates HTR2_PWR_CYCLE to the spacecraft.",
        [
            _step(
                TRANSMIT_STEP_TITLE,
                "Select the command mnemonic and complete this step to "
                "radiate. A command event lands on the GOCE-7 timeline; "
                "expect fault-log ACK within one telemetry frame.",
                _form(
                    [
                        p.FormField(
                            id="command_mnemonic",
                            single_enum=p.SingleEnumField(
                                label="Command mnemonic",
                                options=[COMMAND_NAME],
                                buttons=p.EnumFieldButtonsInputType(),
                                is_required=True,
                            ),
                        ),
                        p.FormField(
                            id="command_sequence",
                            label="Uplink sequence number",
                            int=p.IntField(label="Uplink sequence number"),
                        ),
                    ],
                    is_required=True,
                    completion_action_configs=[
                        p.CompletionActionConfig(
                            create_event=p.CreateEventConfig(
                                name=f"CMD {COMMAND_NAME} transmitted — {FAULT_SATELLITE}",
                                description="Corrective command radiated via "
                                "ground segment. Heater controller power "
                                "cycle; expect bus recovery tau ~45 s.",
                                labels=["GOCE", "command", "HTR-2"],
                                asset_references=[goce7],
                            )
                        ),
                        # The uplink itself: fires the "procedures" webhook
                        # integration -> goce_webhook_receiver.py (ngrok) ->
                        # command_state.json -> streamers heal GOCE-7.
                        p.CompletionActionConfig(
                            send_notification=p.SendNotificationConfig(
                                integrations=p.MultiIntegrationReference(
                                    list=p.MultiIntegrationReference.IntegrationReferenceList(
                                        references=[
                                            p.IntegrationReference(
                                                rid=WEBHOOK_INTEGRATION_RID
                                            )
                                        ]
                                    )
                                ),
                                title=p.StringReference(
                                    constant=f"CMD {COMMAND_NAME} — {FAULT_SATELLITE}"
                                ),
                                message=p.StringReference(
                                    constant=(
                                        f"UPLINK {COMMAND_NAME} sat={FAULT_SATELLITE} "
                                        "src=anomaly_response_procedure"
                                    )
                                ),
                            )
                        ),
                    ],
                ),
            ),
            _step(
                "Confirm command acceptance",
                "Watch the live fault log in the deep-dive workbook: "
                "'CMD HTR2_PWR_CYCLE accepted — power-cycling heater "
                "controller'.",
                _form(
                    [
                        p.FormField(
                            id="cmd_ack",
                            checkbox=p.CheckboxField(
                                label="fsw.event_log shows command accepted",
                                is_required=True,
                            ),
                        )
                    ],
                    completion_action_configs=[
                        p.CompletionActionConfig(
                            create_event=p.CreateEventConfig(
                                name=f"CMD {COMMAND_NAME} acceptance confirmed — {FAULT_SATELLITE}",
                                description="Spacecraft fault log shows the "
                                "power-cycle command accepted; heater duty "
                                "returning to closed-loop control.",
                                labels=["GOCE", "command", "HTR-2"],
                                asset_references=[goce7],
                            )
                        )
                    ],
                ),
            ),
        ],
    )

    # --------------------------------------------- 4. recovery verification
    recovery = _section(
        "Recovery verification",
        "Give the bus one recovery time constant, then let telemetry prove "
        "recovery: the gate below cannot be completed until bus current is "
        "back under the warn limit.",
        [
            _step(
                "Recovery soak",
                "Brief hold so the power-cycle takes effect before judging "
                "telemetry (recovery tau ~45 s; the gate below does the "
                "actual waiting).",
                p.NestedProcedureNode.NestedStepNode(
                    wait=p.WaitStep(),
                    success_condition=p.SuccessCondition(
                        timer=p.TimerSuccessCondition(duration_seconds=30)
                    ),
                    completion_action_configs=[
                        p.CompletionActionConfig(
                            create_event=p.CreateEventConfig(
                                name=f"Recovery soak complete — {FAULT_SATELLITE}",
                                description="30 s hold elapsed — telemetry "
                                "ready to judge.",
                                labels=["GOCE", "recovery"],
                                asset_references=[goce7],
                            )
                        )
                    ],
                ),
            ),
            _step(
                "Telemetry recovery gate",
                f"Auto-validating gate: {BUS_CURRENT} must hold below "
                f"{LIMIT_BUS_CURRENT_WARN_A} A (sustained) before this step "
                "can complete. The recovery run is created on completion.",
                p.NestedProcedureNode.NestedStepNode(
                    form=p.FormStep(
                        fields=[
                            p.FormField(
                                id="recovery_confirmed",
                                checkbox=p.CheckboxField(
                                    label="Fleet status row back to green",
                                    is_required=True,
                                ),
                            )
                        ]
                    ),
                    is_required=True,
                    success_condition=p.SuccessCondition(
                        channel_validation=p.ChannelValidationSuccessCondition(
                            channel=p.ChannelLocator(
                                data_source_ref=DATA_REF,
                                channel_name=BUS_CURRENT,
                                asset=goce7,
                            ),
                            comparator=p.ChannelValidationSuccessCondition.COMPARATOR_LESS_THAN,
                            threshold=LIMIT_BUS_CURRENT_WARN_A,
                            timeout_millis=900_000,
                            time_persistence=30,
                            channel_captures=[
                                p.ChannelCaptureConfig(
                                    output_field_id="recovery_bus_current",
                                    capture_moments=[p.CAPTURE_MOMENT_STEP_COMPLETION],
                                )
                            ],
                        )
                    ),
                    completion_action_configs=[
                        p.CompletionActionConfig(
                            create_run=p.CreateRunConfig(
                                run_output_field_id="recovery_run",
                                name=p.StringReference(constant=RECOVERY_RUN_NAME),
                                description=p.StringReference(
                                    constant="Post-command recovery window for "
                                    "GOCE-7 after HTR2_PWR_CYCLE — created by "
                                    "the anomaly response procedure."
                                ),
                                assets=p.MultiAssetReference(
                                    list=p.MultiAssetReference.AssetReferenceList(
                                        references=[goce7]
                                    )
                                ),
                            )
                        ),
                        p.CompletionActionConfig(
                            create_event=p.CreateEventConfig(
                                name=f"Telemetry recovery verified — {FAULT_SATELLITE}",
                                description=f"Channel-validation gate passed: "
                                f"eps.bus.current_a held below "
                                f"{LIMIT_BUS_CURRENT_WARN_A} A sustained — the "
                                "spacecraft, not the operator, closed this step.",
                                labels=["GOCE", "recovery", "HTR-2"],
                                asset_references=[goce7],
                            )
                        ),
                    ],
                ),
            ),
            _step(
                "Close out",
                "Disposition the anomaly and stamp the recovery event. On "
                "completion the ground segment closes the recovery run and "
                "executes the bus-health checklist against it (data review "
                "should be all green). NOTE: the checklist is applied by the "
                "command bridge, not an in-procedure action — the recovery "
                "run is still open-ended when this step completes, and "
                "checklist execution needs a bounded run window.",
                p.NestedProcedureNode.NestedStepNode(
                    form=p.FormStep(
                        fields=[
                            p.FormField(
                                id="disposition",
                                label="Disposition / follow-up actions",
                                text=p.TextField(
                                    label="Disposition / follow-up actions",
                                    markdown=p.TextFieldMarkdownInputType(),
                                ),
                            )
                        ]
                    ),
                    is_required=True,
                    completion_action_configs=[
                        p.CompletionActionConfig(
                            create_event=p.CreateEventConfig(
                                name=f"{FAULT_SATELLITE} recovered — HTR-2 back in closed-loop control",
                                description="Bus current/voltage/temp back in "
                                "limits; heater duty in 6-18% closed-loop band.",
                                labels=["GOCE", "recovery", "HTR-2"],
                                asset_references=[goce7],
                            )
                        ),
                    ],
                ),
            ),
        ],
    )

    return p.NestedProcedure(
        title=PROCEDURE_TITLE,
        description=(
            "Corrective-action procedure for the GOCE-7 HTR-2 heater "
            "controller latch-up: triage the fleet alert, verify root cause "
            "against the TVAC ground test, transmit HTR2_PWR_CYCLE, and "
            "verify recovery with a telemetry-gated close-out that executes "
            "the bus-health checklist on an auto-created recovery run."
        ),
        steps=[triage, rca, commanding, recovery],
        new_global_fields=[
            p.FormField(
                id="operator_callsign",
                label="Operator callsign",
                text=p.TextField(
                    label="Operator callsign", simple=p.TextFieldSimpleInputType()
                ),
            ),
            p.FormField(
                id="ground_station",
                single_enum=p.SingleEnumField(
                    label="Ground station",
                    options=["Svalbard", "Troll", "Kiruna", "Wallops"],
                    dropdown=p.EnumFieldMenuInputType(),
                    allow_custom=True,
                ),
            ),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="space_demo_prod")
    args = parser.parse_args()

    client = NominalClient.from_profile(args.profile)
    b = client._clients
    print(f"Authenticated as: {client.get_user().email}")

    assets = client.search_assets(search_text=FAULT_SATELLITE, properties={"asset_id": FAULT_SATELLITE})
    asset = next(a for a in assets if a.name == FAULT_SATELLITE)
    workspace = b.resolve_default_workspace_rid()

    channel = create_grpc_channel(
        api_base_url=b._api_base_url,
        service_config=b._service_config,
        user_agent=b._user_agent,
        auth_header=b.auth_header,
        header_provider=b.header_provider,
    )
    proc = ProceduresServiceStub(channel)

    nested = build_nested(asset.rid)
    parsed = proc.ParseNestedProcedure(
        p.ParseNestedProcedureRequest(nested_procedure=nested, include_display_graph=True)
    )
    state = parsed.procedure.state
    print(f"Parsed OK (nodes in graph: {len(state.nodes)})")

    # Upsert: search for an existing procedure with this title.
    existing_rid = None
    try:
        resp = proc.SearchProcedures(
            p.SearchProceduresRequest(
                query=p.ProcedureSearchQuery(search_text=PROCEDURE_TITLE),
                page_size=50,
            )
        )
        for meta in resp.procedure_metadata:
            if getattr(meta, "title", "") == PROCEDURE_TITLE:
                existing_rid = meta.rid
                break
    except Exception as e:
        print(f"Search failed ({e}); creating new")

    if existing_rid is None:
        created = proc.CreateProcedure(
            p.CreateProcedureRequest(
                title=PROCEDURE_TITLE,
                description=nested.description,
                state=state,
                workspace=workspace,
                commit_message="Initial: 4-section anomaly response with "
                "telemetry-gated recovery and checklist close-out",
                is_published=True,
            )
        )
        rid = created.procedure.rid
        print(f"Created procedure: {rid}")
    else:
        rid = existing_rid
        got = proc.GetProcedure(p.GetProcedureRequest(rid=rid))
        latest = got.procedure.commit or None
        # Commit with the state INLINE. A Commit without `state` after a
        # SaveWorkingState commits an EMPTY graph (0 nodes — the app then
        # shows the procedure as invalid), so never rely on the working
        # state being picked up implicitly.
        proc.Commit(
            p.CommitRequest(
                rid=rid,
                branch="main",
                latest_commit_on_branch=latest,
                message="Converge from goce_procedure_builder.py",
                state=state,
            )
        )
        print(f"Committed new revision on: {rid}")

    check = proc.GetProcedure(p.GetProcedureRequest(rid=rid))
    print(f"Verified title: {check.procedure.metadata.title!r}")
    print(f"\nProcedure URL: https://app.gov.nominal.io/w/{workspace}/procedures/{rid}")
    print(f"Transmit step title (bridge watches this): {TRANSMIT_STEP_TITLE!r}")


if __name__ == "__main__":
    main()
