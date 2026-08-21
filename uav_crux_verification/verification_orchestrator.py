#!/usr/bin/env python3
"""The verification campaign orchestrator — runs the whole catalog hands-free.

NATIVE-ACTIONS edition: runs and checklist executions are performed by the
PROCEDURE's own completion actions (create_run + apply_checklists), never by
this code. This orchestrator only:
- commits each procedure's scenario-window constants before its execution
  (TimestampReference(field_id) does not resolve from form fields server-side
  — probed 2026-08-21 — so dynamic windows must be commit-time constants);
- paces steps on a fixed command cadence so the committed windows hold;
- reads each data review's outcome and submits the GO/NO-GO verify step on
  pass or errors it on fail (procedures have no native review-outcome
  success condition);
- sequences requirements and trees, and alerts.

Scheduling policy (user-specified):
- Phase A: subsystem/component requirements. The five system trees run in
  PARALLEL; inside one tree requirements run SEQUENTIALLY, bottom-up.
- Barrier: system-level requirements start only after EVERY phase-A
  requirement passed.
- Phase B: the five system requirements, in parallel.

Webhook fallback: if no scenario shows up within WEBHOOK_GRACE_S of the
command step submitting, the orchestrator queues the scenario itself and
notes the degraded path (same idempotent shape the receiver writes).

Usage:
  python3 -u verification_orchestrator.py run                # full campaign
  python3 -u verification_orchestrator.py run --trees SYS-REQ-004
  python3 -u verification_orchestrator.py single --requirement PAY-REQ-001
"""

from __future__ import annotations

import argparse
import json
import pathlib
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from nominal.core import NominalClient
from nominal.core._utils.grpc_tools import create_grpc_channel
from nominal.protos.procedures.executions.v1 import procedure_executions_pb2 as pe
from nominal.protos.procedures.executions.v1.procedure_executions_pb2_grpc import (
    ProcedureExecutionsServiceStub,
)
from nominal.protos.procedures.v1 import procedures_pb2 as p
from nominal.protos.procedures.v1.procedures_pb2_grpc import ProceduresServiceStub

from alerting import Alerter
from command_file import locked_update, read_state
from crux_kv import load_doc
from procedure_builder import build_nested, checklist_rids_by_requirement
from staging_env import (
    CRUX_PROJECT_PROPERTY,
    CRUX_PROJECT_VALUE,
    PROFILE,
    TEST_CASE_KEY_PROPERTY,
    WORKSPACE_URL,
)
from uav_catalog import Catalog, Requirement, load_catalog
from uav_limits import SCENARIO_WINDOW_S

RIDS_PATH = pathlib.Path(__file__).parent / "uav_rids.json"
CAMPAIGN_PROPERTY = "verification_campaign"
CAMPAIGN_VALUE = "rtx-uav"
WEBHOOK_GRACE_S = 25.0

# Command cadence: one test case every CADENCE_S. The committed run window is
# [cmd_at - 2, cmd_at + WINDOW_END_OFFSET_S]; the 45 s scenario plays ~3 s
# after the command step submits, so the window holds with ≥30 s of drift
# tolerance, and the next scenario never overlaps the previous window.
CADENCE_S = 110.0
WINDOW_END_OFFSET_S = 62.0
CAPTURE_SETTLE_S = 4.0
MAX_CMD_DRIFT_S = 35.0


class WindowDriftError(RuntimeError):
    """The cycle overran its cadence; the committed window no longer holds."""


class CampaignFailure(Exception):
    def __init__(self, requirement: Requirement, tc_ext: str, detail: str, links: dict):
        super().__init__(detail)
        self.requirement = requirement
        self.tc_ext = tc_ext
        self.detail = detail
        self.links = links


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


class RequirementRunner:
    """Owns one thread's Nominal clients; runs requirements sequentially."""

    def __init__(self, campaign_id: str, log_prefix: str):
        self.campaign_id = campaign_id
        self.prefix = log_prefix
        self.client = NominalClient.from_profile(PROFILE)
        b = self.client._clients
        channel = create_grpc_channel(
            api_base_url=b._api_base_url,
            service_config=b._service_config,
            user_agent=b._user_agent,
            auth_header=b.auth_header,
            header_provider=b.header_provider,
        )
        self.execs = ProcedureExecutionsServiceStub(channel)
        self.procs = ProceduresServiceStub(channel)
        self.rids = json.loads(RIDS_PATH.read_text())

    def log(self, message: str) -> None:
        print(f"[{datetime.now():%H:%M:%S}] {self.prefix} {message}", flush=True)

    # ── gRPC step helpers ────────────────────────────────────────────────
    def _exec_state(self, exec_rid: str):
        return self.execs.GetProcedureExecution(
            pe.GetProcedureExecutionRequest(procedure_execution_rid=exec_rid)
        ).procedure_execution.state

    def _step_ids(self, exec_rid: str) -> dict[str, str]:
        state = self._exec_state(exec_rid)
        out = {}
        for node_id in state.nodes:
            node = state.nodes[node_id]
            if node.WhichOneof("node") == "step":
                out[node.step.template_node_id] = node_id
        return out

    def _step_state(self, exec_rid: str, step_id: str) -> str:
        return self._exec_state(exec_rid).nodes[step_id].step.state.WhichOneof("state")

    def _submit_step(self, exec_rid: str, step_id: str) -> None:
        # The server auto-starts a step when its predecessor submits, so our
        # explicit not_started→in_progress transition can race it — treat
        # "Invalid step transition" on that hop as already-started. The submit
        # itself gets one retry after re-checking state for the same reason.
        import grpc

        if self._step_state(exec_rid, step_id) == "not_started":
            try:
                self.execs.UpdateStep(
                    pe.UpdateStepRequest(
                        procedure_execution_rid=exec_rid,
                        step_id=step_id,
                        target_state=pe.TargetStepStateRequest(
                            in_progress=pe.StepInProgressRequest()
                        ),
                    )
                )
            except grpc.RpcError as err:
                if err.code() != grpc.StatusCode.INVALID_ARGUMENT:
                    raise
        submit = pe.UpdateStepRequest(
            procedure_execution_rid=exec_rid,
            step_id=step_id,
            value=pe.StepContentValue(
                form=pe.FormStepValue(
                    fields=[pe.FormFieldValue(checkbox=pe.CheckboxFieldValue(value=True))]
                )
            ),
            target_state=pe.TargetStepStateRequest(submitted=pe.StepSubmittedRequest()),
        )
        for attempt in (1, 2):
            try:
                self.execs.UpdateStep(submit)
                return
            except grpc.RpcError as err:
                if err.code() != grpc.StatusCode.INVALID_ARGUMENT:
                    raise
                time.sleep(2.0)
                state = self._step_state(exec_rid, step_id)
                if state in ("submitted", "succeeded"):
                    return
                if attempt == 2:
                    raise

    def _error_step(self, exec_rid: str, step_id: str, reason: str) -> None:
        if self._step_state(exec_rid, step_id) == "not_started":
            self.execs.UpdateStep(
                pe.UpdateStepRequest(
                    procedure_execution_rid=exec_rid,
                    step_id=step_id,
                    target_state=pe.TargetStepStateRequest(
                        in_progress=pe.StepInProgressRequest()
                    ),
                )
            )
        self.execs.UpdateStep(
            pe.UpdateStepRequest(
                procedure_execution_rid=exec_rid,
                step_id=step_id,
                target_state=pe.TargetStepStateRequest(
                    errored=pe.StepErroredRequest(error_reason=reason[:500])
                ),
            )
        )

    # ── scenario plumbing ────────────────────────────────────────────────
    def _wait_for_ack(self, requirement_ext: str, tc_ext: str, since: float) -> dict:
        """Wait for the streamer's ack for (requirement, tc); fall back to
        queueing the scenario directly if the webhook never lands."""
        deadline = time.time() + WEBHOOK_GRACE_S
        queued_fallback = False
        while True:
            state = read_state()
            for sid, ack in (state.get("acks") or {}).items():
                if (
                    ack.get("requirement_ext") == requirement_ext
                    and ack.get("test_case_id") == tc_ext
                    and ack.get("start_epoch", 0) >= since - 5
                ):
                    locked_update(lambda s: s["acks"].pop(sid, None))
                    return ack
            live = any(
                s.get("requirement_ext") == requirement_ext
                and s.get("test_case_id") == tc_ext
                for s in (state.get("scenarios") or {}).values()
            )
            if not live and not queued_fallback and time.time() > deadline:
                queued_fallback = True
                sid = str(uuid.uuid4())
                self.log(
                    f"⚠ webhook missing for {requirement_ext}/{tc_ext} after "
                    f"{WEBHOOK_GRACE_S:.0f}s — queueing scenario directly (fallback)"
                )
                locked_update(
                    lambda s: s["scenarios"].__setitem__(
                        sid,
                        {
                            "id": sid,
                            "requirement_ext": requirement_ext,
                            "test_case_id": tc_ext,
                            "window_s": SCENARIO_WINDOW_S,
                            "queued_at": datetime.now().isoformat(),
                            "source": "orchestrator-fallback",
                        },
                    )
                )
            if time.time() > since + WEBHOOK_GRACE_S + SCENARIO_WINDOW_S * 2 + 60:
                raise TimeoutError(
                    f"no scenario ack for {requirement_ext}/{tc_ext} — is uav_streamer.py running?"
                )
            time.sleep(1.5)

    # ── native-action plumbing ───────────────────────────────────────────
    def _wait_actions(self, exec_rid: str, step_id: str, timeout_s: float = 90.0) -> None:
        """Block until every completion action on the step reports succeeded;
        raise with the server's own error text if one fails."""
        deadline = time.time() + timeout_s
        while True:
            node = self._exec_state(exec_rid).nodes[step_id].step
            states = [
                (s.state.WhichOneof("state"), getattr(s.state, "error", ""))
                for s in node.completion_action_statuses
            ]
            if states and all(kind == "succeeded" for kind, _ in states):
                return
            failed = [err for kind, err in states if kind == "error"]
            if failed:
                raise RuntimeError(f"procedure completion action failed: {failed}")
            if time.time() > deadline:
                raise TimeoutError(f"completion actions still pending: {states}")
            time.sleep(2.0)

    def _find_native_run(self, exec_rid: str, tc_ext: str, timeout_s: float = 60.0):
        """The run born by the procedure's create_run action — recognized by
        the procedureExecutionRid property the platform stamps on it."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            for run in self.client.search_runs(
                properties={TEST_CASE_KEY_PROPERTY: tc_ext, "campaign_run": self.campaign_id}
            ):
                if (run.properties or {}).get("procedureExecutionRid") == exec_rid:
                    return run
            time.sleep(2.5)
        raise TimeoutError(f"no procedure-created run appeared for {tc_ext}")

    def _await_review(self, run, timeout_s: float = 150.0):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            reviews = list(self.client.search_data_reviews(runs=[run.rid]))
            if reviews:
                return reviews[0].poll_for_completion()
            time.sleep(3.0)
        raise TimeoutError(f"no data review appeared on run {run.rid}")

    # ── the requirement loop ─────────────────────────────────────────────
    def run_requirement(self, req: Requirement, catalog: Catalog, checks: dict) -> None:
        """One retry on window drift — a fresh commit resets the schedule."""
        try:
            self._run_requirement_once(req, catalog, checks)
        except WindowDriftError as drift:
            self.log(f"{req.external_id}: {drift} — retrying with a fresh schedule")
            self._run_requirement_once(req, catalog, checks)

    def _run_requirement_once(self, req: Requirement, catalog: Catalog, checks: dict) -> None:
        checklist_rid = checks[req.id]["publish"]["checklistRid"]
        procedure_rid = self.rids["procedure_rids"][req.external_id]
        test_cases = sorted(
            (catalog.test_cases[tc_id] for tc_id in req.test_case_ids),
            key=lambda tc: tc.external_id,
        )

        # Commit this execution's scenario windows as constants, then create
        # the execution on that commit.
        t0 = time.time() + 5.0
        cmd_at = {tc.external_id: t0 + i * CADENCE_S for i, tc in enumerate(test_cases)}
        windows = {
            ext: (at - 2.0, at + WINDOW_END_OFFSET_S) for ext, at in cmd_at.items()
        }
        nested = build_nested(
            req,
            catalog,
            self.rids["asset_rid"],
            self.rids["uplink_integration_rid"],
            checklist_rid,
            windows=windows,
            campaign_id=self.campaign_id,
        )
        parsed = self.procs.ParseNestedProcedure(
            p.ParseNestedProcedureRequest(nested_procedure=nested)
        )
        current = self.procs.GetProcedure(p.GetProcedureRequest(rid=procedure_rid))
        committed = self.procs.Commit(
            p.CommitRequest(
                rid=procedure_rid,
                latest_commit_on_branch=current.procedure.commit,
                message=f"Campaign {self.campaign_id}: scenario windows for {req.external_id}",
                state=parsed.procedure.state,
            )
        )
        commit_id = committed.procedure.commit
        created = self.execs.CreateProcedureExecution(
            pe.CreateProcedureExecutionRequest(
                procedure_rid=procedure_rid,
                procedure_commit_id=commit_id,
                title=f"{req.external_id} — campaign {self.campaign_id}",
                start_immediately=True,
            )
        )
        exec_rid = created.procedure_execution.rid
        exec_url = f"{WORKSPACE_URL}/procedures/execution/{exec_rid}"
        self.log(f"{req.external_id}: execution {exec_rid}")
        step_ids = self._step_ids(exec_rid)

        for tc in test_cases:
            cmd_step = step_ids[f"cmd_{_slug(tc.external_id)}"]
            capture_step = step_ids[f"capture_{_slug(tc.external_id)}"]
            score_step = step_ids[f"score_{_slug(tc.external_id)}"]
            verify_step = step_ids[f"verify_{_slug(tc.external_id)}"]

            # Pace to the committed schedule.
            wait = cmd_at[tc.external_id] - time.time()
            if wait > 0:
                time.sleep(wait)
            drift = time.time() - cmd_at[tc.external_id]
            if drift > MAX_CMD_DRIFT_S:
                raise WindowDriftError(
                    f"{tc.external_id} command is {drift:.0f}s late for its committed window"
                )

            submit_time = time.time()
            self._submit_step(exec_rid, cmd_step)
            self.log(f"{req.external_id}/{tc.external_id}: scenario commanded (webhook)")
            ack = self._wait_for_ack(req.external_id, tc.external_id, submit_time)

            # Native capture: create_run + apply_checklists fire on submit.
            window_end = windows[tc.external_id][1]
            hold = max(ack["end_epoch"], window_end) + CAPTURE_SETTLE_S - time.time()
            if hold > 0:
                time.sleep(hold)
            self._submit_step(exec_rid, capture_step)
            self._wait_actions(exec_rid, capture_step)
            run = self._find_native_run(exec_rid, tc.external_id)
            self.log(f"{req.external_id}/{tc.external_id}: run {run.rid} (procedure-created)")
            self._submit_step(exec_rid, score_step)
            self._wait_actions(exec_rid, score_step)

            review = self._await_review(run)
            violations = len(list(review.get_events()))
            if violations == 0:
                self._submit_step(exec_rid, verify_step)
                self.log(f"{req.external_id}/{tc.external_id}: ✅ PASS")
                continue

            reason = (
                f"Checklist execution for {tc.external_id} resolved with "
                f"{violations} violation event(s) against the {req.external_id} check."
            )
            self._error_step(exec_rid, verify_step, reason)
            try:
                self.execs.UpdateProcedureExecution(
                    pe.UpdateProcedureExecutionRequest(
                        procedure_execution_rid=exec_rid, is_aborted=True
                    )
                )
            except Exception as exc:
                self.log(f"(abort flag failed: {exc})")
            self.log(f"{req.external_id}/{tc.external_id}: ❌ FAIL — {violations} violations")
            raise CampaignFailure(
                req,
                tc.external_id,
                reason,
                links={
                    "run": f"{WORKSPACE_URL}/runs/{run.rid}",
                    "data review": review.nominal_url,
                    "procedure execution": exec_url,
                },
            )

        closeout = step_ids[f"closeout_{_slug(req.external_id)}"]
        self._submit_step(exec_rid, closeout)
        self.log(f"{req.external_id}: ✅ requirement verified ({exec_url})")


class TreeWorker(threading.Thread):
    def __init__(self, campaign_id: str, reqs: list[Requirement], catalog, checks, label: str):
        super().__init__(daemon=True, name=label)
        self.reqs = reqs
        self.catalog = catalog
        self.checks = checks
        self.failure: CampaignFailure | None = None
        self.error: Exception | None = None
        self.runner = RequirementRunner(campaign_id, f"[{label}]")

    def run(self) -> None:
        try:
            for req in self.reqs:
                self.runner.run_requirement(req, self.catalog, self.checks)
        except CampaignFailure as failure:
            self.failure = failure
        except Exception as error:  # noqa: BLE001
            self.error = error


def run_phase(campaign_id: str, groups: dict[str, list[Requirement]], catalog, checks) -> list:
    workers = [
        TreeWorker(campaign_id, reqs, catalog, checks, label)
        for label, reqs in groups.items()
        if reqs
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    return [w.failure or w.error for w in workers if w.failure or w.error]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["run", "single"])
    parser.add_argument("--trees", help="comma-separated system requirement externals")
    parser.add_argument("--requirement", help="single mode: one requirement external id")
    parser.add_argument("--skip-system", action="store_true")
    args = parser.parse_args()

    campaign_id = datetime.now().strftime("%Y%m%d-%H%M")
    _, doc = load_doc()
    catalog = load_catalog(doc)
    checks = {c["requirementId"]: c for c in doc["checks"]}
    alerter = Alerter(NominalClient.from_profile(PROFILE))

    if args.mode == "single":
        req = catalog.by_external[args.requirement]
        runner = RequirementRunner(campaign_id, f"[{req.external_id}]")
        try:
            runner.run_requirement(req, catalog, checks)
            print("single requirement: PASS")
        except CampaignFailure as failure:
            links = "\n".join(f"• {k}: {v}" for k, v in failure.links.items())
            alerter.send(
                f"Verification FAILED at {failure.requirement.external_id}",
                f"{failure.detail}\n{links}",
                kind="FAIL",
            )
            raise SystemExit(1)
        return

    roots = catalog.roots
    if args.trees:
        wanted = {t.strip() for t in args.trees.split(",")}
        roots = [r for r in roots if r.external_id in wanted]

    started = time.time()
    total_reqs = sum(len(catalog.tree_schedule(r)) for r in roots)
    alerter.send(
        f"Verification campaign {campaign_id} started",
        f"{len(roots)} requirement trees, {total_reqs} requirements, fully automated. "
        f"Trees: {', '.join(r.external_id for r in roots)}.",
        kind="INFO",
    )

    # Phase A: everything below the system level, trees in parallel.
    phase_a = {
        root.external_id: [r for r in catalog.tree_schedule(root) if r.id != root.id]
        for root in roots
    }
    problems = run_phase(campaign_id, phase_a, catalog, checks)
    if problems:
        _report_problems(alerter, problems, campaign_id)
        raise SystemExit(1)

    if not args.skip_system:
        # Barrier passed — Phase B: the system requirements, in parallel.
        phase_b = {f"{root.external_id}(sys)": [root] for root in roots}
        problems = run_phase(campaign_id, phase_b, catalog, checks)
        if problems:
            _report_problems(alerter, problems, campaign_id)
            raise SystemExit(1)

    minutes = (time.time() - started) / 60
    alerter.send(
        f"Verification campaign {campaign_id} PASSED",
        f"All {total_reqs} requirements across {len(roots)} trees verified "
        f"automatically in {minutes:.1f} min — every test case commanded, run, "
        "checked, and rolled up with zero operator intervention. "
        f"Requirements dashboard: {WORKSPACE_URL}/nova (Crux Lite).",
        kind="PASS",
    )


def _report_problems(alerter: Alerter, problems: list, campaign_id: str) -> None:
    for problem in problems:
        if isinstance(problem, CampaignFailure):
            links = "\n".join(f"• {k}: {v}" for k, v in problem.links.items())
            alerter.send(
                f"Campaign {campaign_id} FAILED at {problem.requirement.external_id}",
                f"Requirement: {problem.requirement.external_id} — "
                f"{problem.requirement.title}\nTest case: {problem.tc_ext}\n"
                f"{problem.detail}\n{links}\nCampaign halted; downstream "
                "requirements were not attempted.",
                kind="FAIL",
            )
        else:
            alerter.send(
                f"Campaign {campaign_id} errored",
                f"Orchestrator error: {problem}",
                kind="FAIL",
            )


if __name__ == "__main__":
    main()
