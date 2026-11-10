# Benchmark Space — BZB Engine Acceptance Demo

**Audience:** Benchmark Space lead propulsion engineer + team (technical)
**Length:** ~20 min + Q&A · **Env:** `app.gov.nominal.io`, workspace `space` (cerulean-staging `0e49de18…`)
**Their ask:** *"Look across the last N units, identify the C1 burn, calculate C-star / C-star efficiency, perform statistics across those tests."* Plus custom fluids (REFPROP) and user-defined propulsion formulas over raw data.

---

## The demo world

- **10 BZB engine assets**: the **original BZB Rocket** (real Boomie Zoomie B Hotfire 2 data, June 2025) and nine production units **SN-001…SN-009**.
- **One acceptance hotfire run per asset.** The nine production tests are **single full-duration burns with the same profile as the original Hotfire 2** — so the overlay reads as ten runs of one test procedure. Nothing is pre-labeled: the burn is identified live from raw data (Pc > 260 psi sustained ≥ 3 s) in all ten runs, including the original.
- **SN-008 is the outlier**: eroded ox injector — ΔP collapsed to ~21 psi, ox-rich MR 2.90, rough Pc, η_c* 89% (below the 90% ATP line).
- Every run carries a **T-0 ignition event**.

## Links

| Artifact | URL |
|---|---|
| **Acceptance workbook** — "BZB Fleet — Engine Acceptance Review (10 units)" | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/workbooks/ri.scout.cerulean-staging.notebook.42110ad8-beb6-4b5f-a30e-0bd2485f09b9 |
| SN-008 deep-dive workbook | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/workbooks/ri.scout.cerulean-staging.notebook.cf97382b-542f-4b7f-aa45-6f19d6f56ca5 |
| ATP checklist (7 checks incl. REFPROP consistency) | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/checklists/ri.scout.cerulean-staging.check-collection.b4b39368-428e-4844-a892-cc9651fe1cbf |
| Data reviews | SN-008 run → 5 failures · SN-003 run → clean (run pages → checklist executions tab) |
| Original BZB Rocket asset | https://app.gov.nominal.io/w/ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e/assets/ri.scout.cerulean-staging.asset.30165ee5-a5e5-4b94-a1ea-f8b01c97af67 |

## Pre-demo checklist (15+ min before)

1. **Close any other tabs that have the workbook open** — an open tab keeps an old collaborative session alive and can serve stale content. One clean load, then leave it.
2. Open the workbook (no special URL needed — the runs are clipped to the burn, so it opens framed on the aligned test); click through all 4 tabs once (first paint of 10 aligned series takes ~30–60 s; warmed, instant).
3. Open the SN-008 deep-dive and the SN-008 data review in separate tabs.

---

## Segment 1 — Ten engines, one run each (3 min)

Asset list filtered to "BZB": the original BZB Rocket plus SN-001…SN-009, one acceptance run per unit.

> "Your world, modeled directly: every engine serial is an asset, its acceptance hotfire is a run. The original Boomie Zoomie B and its real Hotfire 2 data sit right beside the production units — same channels, same stand conventions."

## Segment 2 — The T-0 overlay (5 min) ← the money shot

Open the workbook — it lands on the **Acceptance Overlay (T-0)** tab already framed on the burn (runs are clipped to T-0 −5 s → +12 s). A **T-0 event marker** draws on every panel.

> "This workbook has exactly one data input: the **list of those 10 runs**. Each run carries a T-0 ignition event, and the input is aligned to it — so ten hotfires, fired weeks apart across two years, draw on one time axis. Each panel is a single channel or a single calculation; the fan-out into ten colored traces is automatic. No export, no copy, no comparison widget."

- **Pc overlay** with the burn-identification bands: ten identical single-burn profiles stacked at ignition — the original real hotfire indistinguishable from the production units.
- **Injector ΔP**: the pack at ~50 psi, one trace through the 40 psi redline.
- **η_c***: pack at 94–98%, one trace under the 90% line.

> "Nine engines agree with each other — and with the original qual burn. One doesn't. That's SN-008."

## Segment 3 — C1 identification & the c* calc (4 min)

**C1 ID & Performance** tab (markdown explains the method).

> "Nothing was labeled: the *C1 burn* range variable is `Pc > 260 psi sustained ≥ 3 s`, straight off raw data — it finds the burn in all ten runs, including the original 2025 hotfire. c* is the textbook formula as an editable **formula variable**; efficiency divides by ideal c*. Change a constant and all ten runs recompute."

Flows + MR overlay (SN-008 drifting ox-rich), c* overlay, per-run Isp aggregates.

## Segment 4 — Statistics across the tests (3 min)

**Acceptance Statistics** tab: *aggregate-under-ranges* collapses each run's C1 burn to one number per calc.

- Histograms: η_c*, MR, thrust distributions — nine clustered, one out (SN-008).
- Cross-plots: η vs MR and η vs injector ΔP — one point per run; SN-008 sits alone down-right.

## Segment 5 — REFPROP: custom fluids (4 min)

**Fluids (REFPROP)** tab.

> "Cryo density isn't a constant. These panels call **NIST REFPROP equations of state inside Nominal's compute engine** — LOx density from ox feed P/T, methane for the LNG side. Then one line of algebra: predicted injector flow = CdA·√(2ρΔP), overlaid on the flowmeter. On SN-008 the measured ox flow runs ~2× what its ΔP supports — the injector's effective area has grown. That's erosion, detected from fluid properties."

(The original Hotfire 2 has no flow meters, so it appears only on pressure/thrust panels — worth saying out loud; it shows real-data heterogeneity is fine.)

## Segment 6 — Make it automatic + deep dive (4 min)

- **Checklist**: 7 acceptance criteria (η_c* ≥ 90, MR band, injector ΔP ≥ 40, Pc roughness, thrust, He margin during the burn, REFPROP flow-consistency ±20%). Show the two data reviews: SN-003 clean, SN-008 with 5 violations. Offer to run it live on any unit's run.
- **Deep-dive workbook**: SN-008 vs nominal sister SN-007 — injector analysis, Pc spectrum (9 Hz chug line), roughness. The Campaign tab shows SN-008's full stand history pulled from the asset's data scope — the erosion trend that led to this failed test.

> "The fluids checks flag injector erosion even while c* efficiency is still passing — early warning, before the unit fails acceptance outright."

## Close

> "Ten engines including your original qual article, one acceptance run each, every calculation live from raw data — burn identification, c*, REFPROP, statistics, automated acceptance. And everything I clicked is the same API your Python scripts already speak."

## Q&A quick answers

- **Change C1 rule / c* constants live?** Yes — edit the range/formula variable; all runs recompute. Best live moment if asked.
- **Venturis instead of flowmeters?** Same math — ΔP + REFPROP density *is* the venturi equation.
- **REFPROP fluids?** CH4, O2, H2, He, N2, Ar, air, CO2, CO, butane, propane, H2O, Xe; ρ, viscosity, enthalpy, entropy, internal energy, P, T.
- **Add another run to the overlay?** Edit the input's run list — panels fan out automatically.
- **Ingestion?** CSV via Python SDK with tag columns; streaming/TDMS/MCAP also supported.

## Contingencies

- Workbook shows an old title/tabs → a stale collaborative session from an open tab; close ALL tabs with the workbook, wait ~10 min, load once.
- Panels blank at first → 10 aligned series take ~30–60 s on cold cache; the markdown panel gives you something to talk over.
- Overlay looks empty → reset the time window to the run extent (aligned data lives on the earliest run's window, June 17 2025 12:00:00–12:00:17 UTC).
