# GOCE spacecraft operations demo — runbook & talk track

A 30–35 minute end-to-end spacecraft operations demo in the **Space
workspace** (`space_demo_prod`, app.gov.nominal.io), aimed at prospective
spacecraft manufacturing/operations customers. A 25-satellite constellation
streams live telemetry; GOCE-7 suffers a heater-controller latch-up; ops
detects it on the fleet board, root-causes it with live-built UDFs, confirms
the failure mode against TVAC ground-test data, and commands the fix through
a Nominal procedure — whose execution *actually heals the live telemetry*
via a ground-segment command bridge.

**Positioning spine** (informed by the Aug 7 Demo Hot Seat): lead with
**time-to-insight** (days → minutes), show Nominal as **complementary** to
the tools they already run (C2/commanding stacks, bench DAQ, Python
analysis scripts), and keep every feature anchored to what a satellite
engineer actually does during an anomaly.

---

## Resource index (everything lives in space_demo_prod)

| Resource | Name / RID | URL |
|---|---|---|
| Constellation workbook | GOCE constellation: 25-satellite fleet | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/workbooks/ri.scout.cerulean-staging.notebook.4ce102a8-629f-451b-917d-388a937f35a9 |
| RCA deep-dive workbook | GOCE-7: bus health deep-dive | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/workbooks/ri.scout.cerulean-staging.notebook.8013b267-e951-4aaa-8059-b842a367287f |
| Run comparison workbook | GOCE-7 anomaly: flight vs TVAC ground test | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/workbooks/ri.scout.cerulean-staging.notebook.79d27e88-dacc-4380-bfd1-497577ebb8c4 |
| Zoom-down workbook | GOCE-7: telemetry & bus health | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/workbooks/ri.scout.cerulean-staging.notebook.062bbfe2-de63-4798-8e51-66be3b085c6a |
| Checklist (10 checks) | GOCE satellite bus health limits | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/checklists/ri.scout.cerulean-staging.check-collection.25800248-86a1-49f5-8c52-d6f91f26f992 |
| Procedure | GOCE anomaly response: HTR-2 heater runaway (HTR2_PWR_CYCLE) | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/procedures/template/ri.scout.cerulean-staging.procedure.f789cd49-0e68-4d23-b37f-e8d162413c15 |
| Flight anomaly run | GOCE-7 \| Flight EPS anomaly investigation | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/runs/ri.scout.cerulean-staging.run.73f02c8d-6f11-46cd-ae99-a72c1362539d |
| Ground-test run | GOCE-7 \| TVAC HTR-2 anomaly replication (2026-03-14) | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/runs/ri.scout.cerulean-staging.run.e7f4fb3e-a08f-491d-936d-e9ce8c31cc90 |
| Ground-test dataset | GOCE-7 EPS TVAC ground test (2026-03) | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/datasets/ri.catalog.cerulean-staging.dataset.a36dbcd5-8236-490b-87d9-ebcb973aab6c |
| TVAC campaign asset | GOCE-7 FM — TVAC campaign | rid: ri.scout.cerulean-staging.asset.205369f8-49c1-409b-8517-1037ee99f167 |
| Zoom-down template | GOCE satellite zoom-down | rid: ri.scout.cerulean-staging.template.29f2056f-9560-4c7b-8c30-f9122527d4f1 |
| Recovery run (from E2E dry run) | GOCE-7 \| HTR-2 recovery verification | rid: ri.scout.cerulean-staging.run.ae1f9bb0-db64-4633-b8b9-bcf31adfda18 |

Channels use a hierarchical namespace (`.` prefix-tree on the datasets):
`eps.bus.current_a`, `tcs.htr2.duty_cycle_pct`, `gnc.nav.altitude_km`,
`fsw.event_log`, ground-only `gse.tvac.*`. Live data flows into the
**GOCE_Fleet_*** datasets (hierarchical-only; created 2026-08-12):
telemetry+logs `dataset.7fc2eee9-0908-4923-a233-3786736f3f81`,
spacecraft time `dataset.dda69e34-59d9-477e-94d0-f016c106851f`. The
original GOCE_Streaming dataset (mixed old/new names) is dormant and
left for the shared demo-live-streaming service — do not archive it.

## The fault story (one table to memorize)

GOCE-7 payload heater **HTR-2 controller latch-up** — heater FET sticks at
100% duty. Cleared by `HTR2_PWR_CYCLE`. Recovery tau ≈ 45 s.

| Channel | Nominal | Full fault | Red limit |
|---|---|---|---|
| tcs.htr2.duty_cycle_pct | 6–18% closed loop | **pinned 100%** | > 60% sustained 30 s |
| eps.bus.current_a | ~2.4 A | ~3.4 A | > 3.15 A |
| eps.bus.voltage_v | ~3.80 V | ~3.55 V | < 3.60 V |
| eps.payload.current_a | ~0.20 A | ~0.42 A | > 0.35 A |
| tcs.bus.temp_c | ~38.0 °C | ~40.8 °C | > 39.8 °C |
| eps.bus.power_w (UDF) | ~9 W | peaks ~14 W | > 12 W budget |

All limits live in `goce_limits.py` — one source feeds the fleet table
colors, chart redlines, checklist checks, and the procedure's
channel-validation gate ("the limit can't drift between tools" is itself a
talking point).

---

## Pre-demo setup (T-30 min)

From `goce_constellation/` — three long-lived terminals + prep commands:

```bash
# Terminal 1: telemetry streamer (25 satellites; ~2 GB RSS; takes ~90 s to load the CSV)
python3 goce_csv_streamer.py --profile goce_streamer --num-satellites 25
```

```bash
# Terminal 2: fault-aware log streamer
python3 goce_log_streamer.py --profile goce_streamer --num-satellites 25
```

```bash
# Terminal 3: webhook receiver — the "ground segment" (leave visible — it's part of Act 4)
python3 goce_webhook_receiver.py --profile space_demo_prod
```

```bash
# Terminal 4: public tunnel for the webhook (URL changes on every restart!)
cloudflared tunnel --url http://localhost:8765
```

```bash
# EVERY time the tunnel (re)starts: point the "procedures" integration at
# the new trycloudflare URL (grab it from Terminal 4's output):
python3 -c "
from nominal.core import NominalClient
from goce_webhook_receiver import update_integration_url
update_integration_url(NominalClient.from_profile('space_demo_prod'), '<TUNNEL-URL>')"
```

```bash
# Terminal 5: command bridge — now only close-out (bounds recovery run,
# runs the checklist) + silent fallback if the webhook path is down
python3 goce_command_bridge.py --profile space_demo_prod
```

```bash
# Clean state + fresh comparison window (run ~15 min before start):
python3 goce_fault_injector.py reset

# Live checklist evaluation on GOCE-7 (violations -> events + Slack
# #demo-notifications page; add --no-slack to keep it quiet):
python3 goce_streaming_checks.py start --satellites 7

# Create today's procedure execution + pin it into the deep-dive's
# Response tab (procedure panel next to live telemetry). Run BEFORE
# opening the workbook in the browser:
python3 goce_response_prep.py
```

Optional freshness pass (only if you want the flight-anomaly run to show
*today's* fault window): arm the fault ~15 min before the audience arrives,
then `python3 goce_ground_setup.py flight-run --minutes 12` (refreshes the
pinned run's window in place), then either leave the fault armed for Act 1
or `reset` and re-arm on cue.

**Browser tabs to pre-open** (in order): constellation workbook · deep-dive
workbook · run-comparison workbook · checklist · procedure · GOCE-7 asset
page. Log out of nothing, widen the live window to ~15 min on live tabs.

**Timing note**: fault ramp is ~2 min from `arm` to full red; recovery is
~1–2 min after the command. Both are wall-clock, tunable in
`goce_limits.py` (`FAULT_RAMP_S`, `RECOVERY_TAU_S`).

---

## The 30–35 minute talk track

### Cold open (2 min) — the framing

> "You already have a commanding system, bench DAQ, and a pile of Python
> that your best engineers trust. What you don't have is one place where
> flight telemetry, ground-test data, limits, and operational process live
> together — so anomaly response means four tools and a war room. What I'll
> show you is one thread: fleet alert → root cause → ground-test
> corroboration → corrective command → verified recovery. In most ops rooms
> that's a day of work. We'll do it in half an hour, live."

Mention the data path once, up front (the #1 prospect question): *"Behind
this demo is exactly what your integration would look like: a Python
streamer pushing live telemetry through our SDK, plus historical CSV bench
data uploaded as-is. Our mission-ops team builds these pipelines with you
during a trial."*

### Act 1 — Fleet monitoring (6 min) · constellation workbook

1. **Earth view tab**: 25 live ground tracks + 3D globe + fleet altitude.
   **Orbit tab**: the ECEF X/Y scatter draws the constellation's five
   planes as a pole-on ring — a genuine "whoa" visual.
   *Talking point*: every panel is driven by the same live channels your
   MOC displays consume — Nominal isn't replacing your C2; it's the
   analysis and process layer on top of the same stream.
2. **Channel tree** (open the dataset side panel briefly): hierarchical
   namespace `eps.* / tcs.* / aocs.* / gnc.* / fsw.*`. *Talking point*:
   your existing mnemonic database maps in at ingestion — engineers browse
   by subsystem, not by memorized telemetry IDs.
   **Data-architecture point (say it here, at the tree)**: all 25
   satellites stream into **one dataset** — every point tagged
   `satellite=GOCE-N` at ingestion. An asset is a *view*: GOCE-7's data
   scope filters the fleet firehose down to the points that spacecraft
   actually produced. That's why discovery is seamless — same channel
   names on every bird, one place to look, and satellite 26 is a new tag
   value, not a new pipeline, schema, or dashboard. Every workbook you'll
   see today is built on those asset-scoped views.
3. **Fleet status tab** — the money shot: 25 asset-named rows (GOCE-1…25
   row headers) × 4 limit-colored columns, with the fleet EPS traces and
   GOCE-7's live log stacked beside the grid. Wall of green.
   *Talking point*: "one workbook, 25 assets — this scales by tag, not by
   copy-paste. Row 26 is a config change, not a new dashboard."
4. **Trigger the anomaly** (offstage terminal, or pre-armed):

```bash
python3 goce_fault_injector.py arm --event
```

   Within ~2 min GOCE-7's row walks green → yellow → red — and because
   the **streaming checklist** is armed, limit violations start landing
   on GOCE-7's timeline as events automatically, before anyone touches
   anything. The `--event` flag additionally drops the ops-alert event.
   *Events talking point #1*: "Alerts here aren't ephemeral toasts — they're
   **events**: durable, labeled, attached to the asset, and they can fan out
   to Slack or Jira so the on-call engineer gets paged in the tools you
   already use. Three sources, one timeline: automated checklist
   violations, operator annotations, and process milestones."
5. **The Slack hop (the Act 1 → Act 2 transition — play the on-call
   engineer)**: the same violations page **#demo-notifications** in
   Slack. Switch to Slack on screen, let the alert land, and click its
   link — it opens the violation/alert view in Nominal, already on
   GOCE-7. *"I wasn't watching a dashboard. Slack told me, and one click
   put me on the spacecraft with the offending channel in front of me."*
6. **Show the source checklist** (from the alert view, follow the
   checklist provenance — or open the pre-staged tab): **GOCE satellite
   bus health limits**, 10 checks. *Talking point*: "This checklist IS
   the alarm database — the same limits color the fleet grid, page
   Slack, and gate the recovery procedure you'll see later. It's
   versioned like code: a limit change is a reviewed, published
   revision, not someone editing a config file on a console. And it runs
   everywhere — continuously against this live stream, and on demand
   against any archived run" (which is exactly what Act 3 does with the
   flight anomaly run and Act 4 does with the recovery run).
   From the alert view / asset context, open **GOCE-7: bus health
   deep-dive** → Act 2.

### Act 2 — Drill-down & root cause (9 min) · deep-dive workbook

Open **GOCE-7: bus health deep-dive → EPS anomaly (RCA)** tab.

1. Read the symptoms off the panels: current stepped ~1 A, voltage sagging
   through the redline, bus temp climbing, and the **live fault log**
   narrating (`HTR-2 heater duty cycle at 100% — DUTY_SET command timeout`).
   *Talking point*: logs and numeric telemetry in one view — no separate
   log aggregator hop during triage.
2. **Live-build UDF #1** (warm-up, ~2 min): create a derived variable
   `eps.bus.power_w = eps.bus.voltage_v × eps.bus.current_a`.
   > "Bus power isn't telemetered. I don't file a ticket with the FSW team
   > — I derive it, right here, from first principles. Nominal ~9 W… and
   > there's the anomaly riding ~3 W high. Three watts is exactly HTR-2's
   > rated draw. And look — its duty cycle is pinned at 100%."
3. **Live-build UDF #2** (the flex, ~3 min): Stefan–Boltzmann radiator
   equilibrium — *a real physical law with real constants, composed from
   stock compute nodes*:
   > "A radiator in vacuum rejects P = ε·σ·A·T⁴. Invert it: T_eq =
   > (P/(ε·σ·A))^¼ − 273.15. σ is a constant of nature; ε and A come from
   > our thermal model. Multiply → scale → √ → √ → offset. Sanity check: at
   > nominal power the law predicts −25 °C, which is exactly what the
   > radiator measures — the model is honest. At fault power it predicts
   > −10 °C or warmer, but the radiator still reads −25: **the spacecraft
   > physically cannot reject this heat. Thermal control can't save it —
   > the heater has to be commanded off.**"
   *Complementary-tools point*: "If this math already lives in a Python
   script you trust, you don't rebuild it — scripts run at ingestion or the
   logic composes here in-product; both become standardized, versioned
   workflow instead of a file on someone's laptop."
4. Point at the pre-saved versions of both UDFs on the tab: "and once
   saved, they're shared — the next engineer inherits the derivation, not
   a screenshot."

### Act 3 — Ground-test corroboration (7 min) · run comparison + checklist

Open **GOCE-7 anomaly: flight vs TVAC ground test**.

1. Overview panel tells the story; then the overlays: flight (red) vs the
   March TVAC bench replication (blue). Identical signature — duty pinned,
   +1.0 A step, −0.25 V sag.
   *Talking point*: "Your test campaign data doesn't retire when the bird
   ships. TVAC, EMI, bench — it stays queryable next to flight data
   forever. The RCA answer was already in your archive."
2. **Distributions & signatures tab**: histograms and the V-I / duty-power
   signature plots — time-independent, so a March bench test and an August
   flight anomaly overlay perfectly without timestamp gymnastics.
3. Show the **flight data review** (checklist executions tab on the flight
   anomaly run): 6 red / 4 green, each violation window an **event** with
   labels. *Events talking point #2*: "This is automated disposition — the
   same 10 limits every time, versioned like code, executable against any
   run or any satellite. Review-by-exception instead of
   scroll-every-channel."
   > "So: known failure mode, characterized on the bench, with a known
   > corrective action — `HTR2_PWR_CYCLE`. What was a mystery five minutes
   > ago is now a commanding decision with paperwork."

### Act 4 — Corrective action & verified recovery (9 min) · Response tab

Stay in the deep-dive workbook: the **Response** tab embeds the live
procedure execution (pinned by `goce_response_prep.py`) beside the HTR-2
duty trace, the bus-current recovery-gate channel, and the command-ACK
log — *you work the procedure and watch your actions land in the
telemetry on one screen*. Walk it as the operator:

1. **Anomaly triage**: alert source, summary, bind asset GOCE-7. *Talking
   point*: forms, captures, and gates — your ops procedures stop being PDFs
   and start producing data.
2. **Root cause verification**: RCA checkboxes → TVAC match → **GO/NO-GO**.
   Click GO: a decision event lands on the timeline (flight-director
   accountability, for free).
3. **Corrective commanding**: complete **"Transmit HTR2_PWR_CYCLE
   command"**. Point at Terminal 3: the step's **Send-notification action
   fires Nominal's webhook integration**, and the ground-segment receiver
   logs the POST and radiates the command within ~3 s — *this is the
   complementary-integration moment*:
   > "Nominal doesn't pretend to be your command system. Completing the
   > step pushes a webhook through our integration layer — the same rail
   > that pages Slack or Opsgenie — and your ground segment (here, a
   > 100-line HTTP receiver) commands through the stack you've already
   > qualified. No polling, no glue code on our side: the procedure step
   > IS the uplink trigger."
   Watch: CMD-transmitted event (from the procedure) + CMD-accepted ACK
   event (from the "spacecraft") + the fault log printing
   `CMD HTR2_PWR_CYCLE accepted`.
4. **Recovery verification**: the 2-min soak, then the **telemetry recovery
   gate** — a channel-validation success condition on
   `eps.bus.current_a < 3.0 A` sustained.
   > "I cannot click past this step. The procedure is watching live
   > telemetry, and it will not let me declare victory until the spacecraft
   > agrees." (Flip to the Fleet status tab: GOCE-7's row walks red →
   > yellow → green while you talk.)
5. **Close out**: disposition notes → recovery run auto-created, bus-health
   checklist executed against it (all green data review), recovery event
   stamped.

### Coda — the asset tells the story (3 min)

Open GOCE-7's asset page → events timeline:

> "**Alert → GO decision → command transmitted → command accepted →
> recovered** — plus every limit violation and the checklist reviews. Six
> months from now, a new engineer asks 'what happened to sat 7 in August?'
> This is the answer. Not a Confluence page someone forgot to write — the
> actual record, attached to the actual data."

Close with repeatability + API-first:
- The zoom-down workbook is a **template** — new satellite, one click.
- Checklists and procedures are **version-controlled** — limit changes are
  deliberate, reviewed, published.
- *"And a meta-point: every resource you just saw — workbooks, checklist,
  procedure, runs — was created through our public API. Whatever we didn't
  build for you, you can build."*

**Q&A hooks to leave open**: batch/historical ingestion of their formats,
alignment of many runs (cycle-style testing), Slack/Jira notification
wiring, multi-tenant/workspace controls.

---

## Dry-run checklist

1. [ ] Both streamers up ≥ 10 min (fleet table fully populated, 25 rows)
2. [ ] Webhook receiver + tunnel up; "procedures" integration repointed at
       today's tunnel URL; bridge running (close-out + fallback)
2b.[ ] Webhook smoke test: `curl -X POST <tunnel-url>` → Terminal 3 logs
       "WEBHOOK RECEIVED" (nominal state → no side effects)
3. [ ] `goce_fault_injector.py status` → `nominal`, envelope 0.000
4. [ ] Fleet status tab: all 25 rows green (give it one full live window)
5. [ ] Six browser tabs pre-opened (order above), live windows ~15 min
6. [ ] Procedure page shows no half-finished execution (archive old ones)
7. [ ] Old `GOCE-7 | HTR-2 recovery verification` runs archived/renamed if
       you want a clean close-out (the bridge picks the *open* one)
8. [ ] Rehearse the two UDF builds — they are the only live-authoring
       moments (bus power: multiply two channels; Stefan–Boltzmann: open
       the saved variable and walk the node chain if you don't want to
       build from scratch)
9. [ ] Time yourself: arm the fault when you *start* Act 1 — it's fully
       red right when you finish the fleet-board pitch

### Mid-demo contingencies

| Symptom | Action |
|---|---|
| Fleet table looks stale | Streamer died (network blip) — relaunch Terminal 1; data resumes into the same datasets in ~60 s |
| Fault won't show | `python3 goce_fault_injector.py status` — if `nominal`, re-arm; ramp is 2 min |
| Webhook didn't fire on transmit | Bridge fallback heals it within ~5 s anyway (audience sees nothing). Post-demo: tunnel died or integration URL stale — repoint it |
| Both webhook AND bridge missed | `python3 goce_fault_injector.py clear` simulates the command and the story continues |
| Recovery gate won't pass | Telemetry needs ~60–90 s under 3.0 A after recovery starts; narrate the soak, flip to Fleet status while waiting |
| Need a hard reset mid-demo | `python3 goce_fault_injector.py reset` → row green in ~1 min; re-arm any time |

### Reset between demos

```bash
python3 goce_fault_injector.py reset
```

Then in-app: archive the demo's procedure execution, the recovery run +
its data review, and the alert/decision/command/recovery events on GOCE-7
(all archive-reversible). Streamers and bridge stay up indefinitely.

---

## Mechanics reference (for whoever runs this next)

- `command_state.json` is the "spacecraft": streamers poll it every ~2 s.
  The injector writes it manually; the **webhook receiver** writes it when
  the transmit step's Send-notification action POSTs through the
  "procedures" integration (`integration.d142937d…`, URL = the cloudflared
  tunnel). The polling bridge is the fallback: if the webhook path is down
  it heals within ~5 s instead of ~3 s, and its state check makes the two
  paths idempotent (whoever arrives second sees "recovering" and no-ops).
- **Tunnel URL is ephemeral** — every `cloudflared` restart mints a new
  `trycloudflare.com` URL and the integration must be repointed (command in
  the setup section). A dead tunnel is invisible until the transmit step
  silently falls back to the bridge — check Terminal 3 logs the POST during
  the dry run.
- Fault envelope: 0→1 ramp over 120 s from arm; exponential decay
  (tau 45 s) from command receipt. Deltas: `goce_limits.FAULT_DELTAS`.
- The 72 h GOCE replay is *natively anomalous* (bus temp to 58 °C, wheels
  to 21 krpm) — the streamer clamps monitored channels into their nominal
  band (`goce_limits.NOMINAL_CLAMPS`) so only the injected fault can cross
  a limit. Per-satellite variance is clamped to ±1% on monitored channels.
- The ground-test CSV is generated from the same `FAULT_DELTAS`
  (`make_ground_test_csv.py`) so flight and bench signatures cannot drift.
- **Data-scope trap**: run-level data-source edits propagate to the
  attached asset (bidirectionally). Never rebind a run that's attached to
  a live-fleet asset — that's why the ground run lives on its own
  "GOCE-7 FM — TVAC campaign" asset.
- Builders (all idempotent, all `--profile space_demo_prod`):
  `constellation_workbook.py`, `goce_deepdive_builder.py`,
  `goce_runcompare_builder.py`, `goce_procedure_builder.py`,
  `goce_ground_setup.py {ground|flight-run}`, `make_ground_test_csv.py`,
  `goce_streaming_checks.py {start|stop}`.
- **Close any browser tab that has a workbook open before re-running its
  builder** — an open app session auto-saves its (stale) state over API
  updates. After a builder run, the app can keep serving the old version
  for ~10+ minutes if a live editing session existed (repeated reloads
  renew the session and make it worse) — leave the workbook closed for
  10 minutes, then open once. Never re-run builders during a demo.
- All workbook tabs are canvas layouts; the fleet grid's asset names are
  value-table row headers (they survive narrow aspect ratios where cell
  labels crop). The embedded checklist panel type exists but is
  flag-gated off in this tenant (checklistReportView) — swap it in when
  the flag ships.
