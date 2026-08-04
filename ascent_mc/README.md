# Ascent MC Build 47 — rocket ascent Monte Carlo demo

Stands up a 10-run rocket ascent Monte Carlo in Nominal per the
[simulation setup docs](https://docs.nominal.io/core/documentation/platform/simulation/setup)
(Track A small campaign: one dataset for the model, three tags on every
point, one first-class run per sim run), plus the analysis artifacts from the
[analysis docs](https://docs.nominal.io/core/documentation/platform/simulation/analysis).

Scenario: two-stage LOX/RP-1 launch vehicle, payload deploy in LEO
(~205 km, ~8.2 km/s). One sim build ("Ascent MC Build 47"), 10 dispersions.
Run 1 is the nominal case; runs 2–10 disperse stage thrust, Isp, propellant
load, drag, and winds.

## Files

| File | Contents |
|---|---|
| `generate_mc_data.py` | Simplified 2-DOF ascent simulator + dispersion sampling; regenerates both CSVs deterministically (seeded) |
| `ascent_mc_build47.csv` | 11,610 rows, all 10 runs. Columns: `time_s` (relative seconds from liftoff), 7 numeric channels, `flight_phase` (enum), and tag columns `model_name`, `sim_number`, `run_number` |
| `ascent_mc_build47_run_metadata.csv` | Per-run dispersion inputs (seed, thrust/Isp/prop-load/drag factors, wind bias) and MECO/SECO/deploy times |
| `stand_up.py` | Creates the `LV-2 GNC simulation` dataset, uploads the CSV (relative-seconds timestamps, 3 tag columns), creates the 10 runs with tag-filtered data scopes, labels, properties, and timeline events |
| `analysis_setup.py` | Creates the analysis artifacts: overlay workbook, comparison workbook, checklist with threshold checks, and checklist executions (data reviews) on all 10 runs |

## Channels (8)

`altitude_m`, `inertial_velocity_mps`, `dynamic_pressure_pa`, `mass_kg`,
`thrust_kn`, `acceleration_mps2`, `flight_path_angle_deg` (numeric) and
`flight_phase` (string enum).

## Usage

Requires a configured nom profile (default name `demo_space_prod`) whose
workspace is the target workspace:

```bash
pip install "nominal>=1.156"
python generate_mc_data.py           # regenerate CSVs (deterministic)
python stand_up.py                   # dataset + upload + 10 runs + events
python analysis_setup.py             # workbooks + checklist + executions
```

Both stand-up scripts are idempotent: they search for existing objects by
name before creating, so reruns don't duplicate.
