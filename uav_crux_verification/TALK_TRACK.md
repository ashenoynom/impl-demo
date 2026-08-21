# Talk Track — Automated Requirements Verification (~12 min live core)

Default cut for the Raytheon Mid-Aft-Tail audience (arc: procedures on rails
→ requirements tracing shown AFTER procedures, per Joe's thread). Timings
assume the short green variant (`--trees SYS-REQ-004`, ~8 min wall) running
UNDER the narration, plus a pre-recorded or pre-run full-catalog end state.
Adjust segments to attendees once the invite list is known.

---

## 0:00 — Cold open: the problem (1 min)

> "Today, closing out a test campaign means an operator driving steps from a
> document, timing work by hand in SAP, transcribing pass/fail into a
> requirements tracker, and chasing raw data when something looks wrong.
> Every hop is manual, every hop loses fidelity. We're going to run an
> entire requirements verification campaign — commanding the test article,
> capturing data, scoring it, rolling it up — with one click."

Screen: Crux Lite, System Level view — five system requirements, not green.

## 1:00 — The catalog is the source of truth (2 min)

- Open SYS-REQ-003 → trace: subsystems (PRP, PWR…) → components. "System
  requirements decompose to subsystem and component requirements; test cases
  verify each level. This structure — not a script — is what drives
  everything you're about to see."
- Open PWR-REQ-001 → its **check**: "The pass criterion is machine-readable,
  authored on the requirement: power margin below 20 % is a violation. And
  it's *published* — this exact check is a checklist in Core. One source,
  two enforcement points: the chart redlines and the scoring."

## 3:00 — The procedure puts it on rails (1.5 min)

- Open "Verify PWR-REQ-001": command step → verify step → close-out.
- > "Generated from the catalog. The command step doesn't tell a human to go
  > run a test — its completion action fires a webhook that commands the
  > test article itself. Same hop your instrumentation or test-stand
  > commanding would take."
- Point at completion actions: events. "Every transition stamps a timestamped
  event — that's your cycle-time record, measured from what actually
  happened, not from a clock someone forgot to stop."

## 4:30 — Execute (30 s) — THE moment

Terminal: `python3 -u verification_orchestrator.py run --trees SYS-REQ-004`

> "That's the operator's entire job for this campaign. One command."

## 5:00 — Watch it run (3 min, narrate over the log + workbook)

- Workbook Overview (GO LIVE): "Live telemetry from the article. Watch the
  detect-and-avoid channels — that sweep is the commanded scenario window."
- Tree tab: run chips appearing on charts. "Each window becomes a run,
  stamped with its test-case ID — that stamp is what ties evidence to
  requirement."
- Procedures app: executions advancing themselves; a data review resolving.
  "The checklist scored the run server-side against the actual samples.
  Nobody transcribed anything."
- Note the ordering: "Components first, then their subsystem, and the
  system-level acceptance only runs after every subsystem underneath it
  passed. Independent trees run in parallel — your V&V order of operations,
  enforced by automation."

## 8:00 — Crux flips green (1.5 min)

- Crux Lite → sync → PASS chips. Open a requirement → its test case → the
  contributing run → the data review. "Requirement to raw telemetry in three
  clicks, and every link was created by the campaign itself."
- Coverage KPI. "This is why we show requirements *after* procedures — now
  you know exactly where these pass/fail records come from."

## 9:30 — The hiccup track (2 min)

- `uav_fault_injector.py arm && verification_orchestrator.py run --trees SYS-REQ-003`
  (or pre-recorded): power margin dips to 12 % mid-scenario.
- The Slack alert lands: requirement, test case, links. Click the data
  review: the violation range highlighted on the trace.
- > "The campaign halted itself — nothing downstream ran against a broken
  > article — and the team got paged with the evidence, not a vague red X.
  > This is exception-only operations: your people look at data only when
  > the data says to."

## 11:30 — Close (30 s)

> "One click, N requirements, zero transcription: commanded, captured,
> scored, rolled up, and alerted. The catalog was the program; Nominal was
> the machine that ran it. For Mid-Aft-Tail, swap this catalog for yours —
> the pipeline regenerates from whatever the requirements say."

---

**Q&A landmines to prep**: DOORS/Jama import path (CSV import exists in
Crux; sync is roadmap) · what the webhook talks to IRL (instro lib / engine
commanding — build-partner conversation per the thread) · multi-article
scale (data-scope input swap) · audit trail (events + changelog + data
reviews are all timestamped and attributable).
