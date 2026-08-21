# Automated Requirements Verification — Demo Runbook

**Story**: An operator clicks Execute once. Procedures verify the entire UAV
requirement catalog hands-free — each test case is commanded onto the live
test article *from the procedure* (webhook uplink), captured as a run,
scored by the requirement's published checklist, and rolled up in Crux.
Subsystems verify before the system requirement they roll up to; the five
system trees run in parallel. Green track: all 36 requirements end green and
the operator gets one "campaign passed" notification. Failure track: the
power-margin requirement (PWR-REQ-001) violates its check mid-campaign, the
procedure fails out, and a Slack alert names the requirement with links to
the failing run / data review / procedure execution.

Everything targets **gov staging**, workspace `…7d802d4e…`, profile
`anish_staging_default`. All scripts live in `impl-demo/uav_crux_verification/`.

---

## Key URLs & RIDs

| Thing | Where |
|---|---|
| Crux Lite (requirements) | Custom apps → **Crux Lite** (project "UAV Demo") |
| Campaign workbook | `uav_rids.json → workbook_url` — "UAV Requirements Verification Campaign" |
| UAV-1 asset | `uav_rids.json → asset_rid` |
| Streaming dataset | `uav_rids.json → dataset_rid` |
| 36 procedures | Procedures app, titled "Verify <REQ> — …"; rids in `uav_rids.json → procedure_rids` |
| 36 checklists | properties `source=crux-lite`, `crux_requirement_external_id` |
| Uplink integration | `verification-uplink` (`uav_rids.json → uplink_integration_rid`) |

## Terminals (start ~15 min before)

All from `impl-demo/uav_crux_verification/`:

```bash
# T1 — live telemetry + scenario engine (leave running)
python3 -u uav_streamer.py

# T2 — webhook receiver (leave running)
python3 -u uav_webhook_receiver.py

# T3 — tunnel (leave running; URL IS EPHEMERAL — repoint after every restart!)
cloudflared tunnel --url http://localhost:8766
# then, once it prints the trycloudflare URL:
python3 uav_webhook_receiver.py --public-url https://<fresh>.trycloudflare.com

# T4 — the campaign (the "operator hits Execute" moment)
python3 -u verification_orchestrator.py run
```

### Pre-demo checklist

1. **Reset the slate** so Crux goes 0 → green live:
   `python3 campaign_reset.py --all`  (archives previous campaign runs,
   clears command file + fault).
2. Confirm streamer is streaming (T1 prints ticks) and the workbook's
   headline value table updates live.
3. Confirm the tunnel is repointed (T3 step above). Sanity: submitting any
   procedure's first step should print `⚡ scenario queued` in T2 within ~3 s.
4. Fault CLEAR for the green take: `python3 uav_fault_injector.py status`.
5. Preload browser tabs: campaign workbook (Overview tab, GO LIVE), Crux Lite
   (System Level view), Procedures list. Load the workbook ONCE, early —
   collaborative-session staleness makes repeated reloads worse.
6. Slack channel open (alerts land there once the Slack integration exists —
   see Alerts below).

## Green-lights track (~20–25 min full catalog)

1. Show Crux Lite: the catalog, the DAG (a system requirement → its
   subsystems → components), statuses not green. Show a requirement's
   **check** (violation triggers) and that it's **published as a checklist**.
2. Show one generated procedure ("Verify PWR-REQ-001 — …"): command step
   (webhook uplink), verify step, close-out — all generated from the catalog.
3. T4: `python3 -u verification_orchestrator.py run` — narrate the parallel
   trees in the log; flip to the workbook: scenario sweeps marching across
   the per-tree tabs, run chips stacking up on the charts.
4. Procedures app: executions completing themselves; events stamping the
   UAV-1 timeline (the cycle-time record). For the in-workbook view, run
   `python3 execution_dashboard.py` ~1 min after the campaign starts (or
   after it ends) — it re-pins the workbook's "Campaign executions" tab to
   this campaign's six hero executions (galaxy's procedure panel binds
   concrete execution rids only, so each campaign needs a repin; keep the
   workbook closed while it runs).
5. Crux Lite: requirements flipping PASS as runs+reviews sync (sync is
   5-min auto; hit "sync now" to force). End state: every requirement green.
6. The "campaign passed" notification arrives (Slack; also an event on
   UAV-1's timeline).

Short variant: `--trees SYS-REQ-004` (~8 min) or
`single --requirement PWR-REQ-001` (~90 s).

## Failure track (~4 min)

```bash
python3 campaign_reset.py --all          # optional: fresh slate
python3 uav_fault_injector.py arm        # PWR-REQ-001 will fail
python3 -u verification_orchestrator.py run --trees SYS-REQ-003
```

PWR-REQ-001's scenario drives `pwr.margin_pct` to ~12 % (check: ≥ 20 %):
the data review resolves with a violation, the verify step errors, the
execution aborts, tree halts before SYS-REQ-003, and the FAIL alert fires
with links to run / data review / procedure execution. Show the alert →
click the data review link → the violation range on the chart.

Afterwards: `python3 uav_fault_injector.py clear` and
`python3 campaign_reset.py --campaign <stamp>` to archive the failing run
(it pins PWR-TC-001 at "failing" in Crux until archived).

## Alerts

`alerting.py` sends through a Nominal **Slack integration** when one exists
(set `slack_integration_rid` in `uav_rids.json`, or it auto-discovers a
Slack integration whose channel contains "verification"). Create one by
opening the Slack OAuth link (regenerate with
`IntegrationsService.generate_slack_webhook_link`) and picking the demo
channel. Until then, alerts print in T4 and land as events on UAV-1.

## Contingencies

| Symptom | Fix |
|---|---|
| T2 never prints `⚡ scenario queued` | Tunnel died / URL stale → restart T3 + repoint. The orchestrator self-heals per test case after 25 s (`orchestrator-fallback` in the log) — demo continues either way. |
| Streamer dies (network blip) | Restart T1. Orchestrator times out the current TC after ~3 min; re-run `single --requirement <the one that died>` then resume. |
| "Invalid step transition" | Auto-start race — retried automatically now; if an execution is stuck, abort it in the app and re-run that requirement `single`. |
| Crux shows a requirement failing after a fault rehearsal | `python3 campaign_reset.py --campaign <stamp>` (archives those runs). |
| Someone's Crux tab freezes ("save conflict") | We wrote the doc while they had it open (seed-time only). They reload and discard. Never run `crux_seed.py`/`checklist_publisher.py` during the demo. |
| Old runs polluting statuses | They're excluded via runExclusions (440 legacy). New foreign runs with `crux_project=UAV` would join scope — re-run `crux_seed.py --apply` (off-demo hours) to exclude. |

## Architecture note: native procedure actions

Runs and checklist executions are performed BY THE PROCEDURE (completion
actions), not by orchestrator code:

- `create_run` on the capture step births the bounded run (properties incl.
  `test_case_id` stamped natively; platform adds `procedureExecutionRid`).
- `apply_checklists` on the following score step executes the requirement's
  checklist against that run — the run reference is **step-qualified**
  (`capture_<tc>.run_<tc>`; a bare field id silently fails).
- The orchestrator only: commits each execution's scenario-window constants
  (server can't resolve `TimestampReference(field_id)` from form fields —
  product gap), paces steps on a 110 s cadence so those windows hold, reads
  each data review's outcome (no native review-outcome success condition
  exists — second product gap), and submits/errors the GO/NO-GO step.

## What was proven live (2026-08-21)

- Crux Lite KV doc read/write from Python (36 checks seeded, exclusions).
- First-ever live firing of crux-lite's checklist-publish recipe
  (trap: omit `checkLineageRid` on commit — including it 400s).
- Procedure send_notification → simple-webhook → local receiver →
  streamer scenario → ack: E2E in seconds, with orchestrator fallback.
- Native create_run + apply_checklists E2E (~75 s/test case); failure
  track: violation → step errored → execution aborted → alert with links.
- Full 36-requirement campaign green in one command (18 min pre-native;
  native cadence ~30-35 min — tune CADENCE_S to compress).
- Crux Lite UI: PASS chips derived purely from campaign runs + reviews.
