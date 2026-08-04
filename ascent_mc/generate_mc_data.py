#!/usr/bin/env python3
"""Generate the LV-2 ascent Monte Carlo dataset (Ascent MC Build 47).

Produces two CSVs next to this script:

- ascent_mc_build47.csv: 10 runs x 1,161 samples (t = 0..580 s @ 0.5 s),
  7 numeric channels + flight_phase, plus the three tag columns
  (model_name, sim_number, run_number) per Nominal's simulation data model.
- ascent_mc_build47_run_metadata.csv: per-run dispersion inputs and key
  event times (MECO / SECO / payload deploy).

Scenario: two-stage LOX/RP-1 launch vehicle, payload deploy in LEO
(~205 km, ~8.2 km/s inertial). Run 1 is the nominal case; runs 2-10
disperse stage thrust, Isp, propellant load, drag, and winds.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent

MODEL_NAME = "LV-2 GNC simulation"
SIM_NUMBER = "Ascent MC Build 47"
NUM_RUNS = 10
DT = 0.5  # sample period, seconds
T_END = 580.0  # seconds after liftoff
BASE_SEED = 4700

G0 = 9.80665
EARTH_ROT_MPS = 408.0  # eastward boost at ~28.5 deg latitude
RHO0 = 1.225
SCALE_HEIGHT_M = 8500.0

# --- Vehicle (nominal) ---
S1_PROP_KG = 148_000.0
S1_DRY_KG = 12_000.0
S1_THRUST_N = 2_900_000.0  # vacuum
S1_ISP_SL = 282.0
S1_ISP_VAC = 311.0

S2_PROP_KG = 30_000.0
S2_DRY_KG = 3_500.0
S2_THRUST_N = 400_000.0
S2_ISP_VAC = 345.0

PAYLOAD_KG = 4_200.0
FAIRING_KG = 900.0  # jettisoned at 210 km dynamic-pressure-free point (~t_meco)

DRAG_AREA_M2 = 10.9
CD = 0.35

SEP_COAST_S = 3.0  # MECO -> separation
IGNITION_DELAY_S = 3.0  # separation -> stage 2 ignition
DEPLOY_COAST_S = 90.0  # SECO -> payload deploy
DEPLOY_PHASE_S = 5.0  # duration flight_phase reads "payload_deploy"


def air_density(alt_m: float) -> float:
    return RHO0 * math.exp(-max(alt_m, 0.0) / SCALE_HEIGHT_M)


def gravity(alt_m: float) -> float:
    r = 6_371_000.0
    return G0 * (r / (r + max(alt_m, 0.0))) ** 2


def pitch_profile(t: float, t_meco: float, t_seco: float) -> float:
    """Prescribed flight-path angle (deg): 90 at liftoff -> ~0 by SECO."""
    if t <= 10.0:
        return 90.0
    if t <= t_meco:
        # gravity turn through stage 1: ease from 90 down to ~20 deg
        f = (t - 10.0) / (t_meco - 10.0)
        return 90.0 - 67.0 * (f**0.85)
    if t <= t_seco:
        # stage 2: bleed the remaining angle to ~0.3 deg
        f = (t - t_meco) / (t_seco - t_meco)
        return 23.0 * (1.0 - f) ** 1.9 + 0.3
    return 0.0


def simulate_run(
    run_number: int,
    thrust_s1_factor: float,
    thrust_s2_factor: float,
    isp_factor: float,
    prop_load_factor: float,
    drag_factor: float,
    wind_bias_mps: float,
) -> tuple[list[dict], dict]:
    s1_prop = S1_PROP_KG * prop_load_factor
    s2_prop = S2_PROP_KG * prop_load_factor
    s1_thrust = S1_THRUST_N * thrust_s1_factor
    s2_thrust = S2_THRUST_N * thrust_s2_factor
    s1_isp_sl = S1_ISP_SL * isp_factor
    s1_isp_vac = S1_ISP_VAC * isp_factor
    s2_isp = S2_ISP_VAC * isp_factor

    # Event times from propellant depletion at the dispersed mass flow.
    s1_mdot = s1_thrust / (s1_isp_vac * G0)
    t_meco = s1_prop / s1_mdot
    t_sep = t_meco + SEP_COAST_S
    t_ign2 = t_sep + IGNITION_DELAY_S
    s2_mdot = s2_thrust / (s2_isp * G0)
    t_seco = t_ign2 + s2_prop / s2_mdot
    t_deploy = t_seco + DEPLOY_COAST_S

    mass = s1_prop + S1_DRY_KG + s2_prop + S2_DRY_KG + PAYLOAD_KG + FAIRING_KG
    fairing_dropped = False

    v = 0.0  # airspeed along velocity vector, m/s
    alt = 0.0
    rows: list[dict] = []
    sim_dt = 0.1  # integration step (finer than the 0.5 s sample grid)

    n_steps = int(round(T_END / sim_dt)) + 1
    sample_every = int(round(DT / sim_dt))

    max_q = 0.0
    for i in range(n_steps):
        t = i * sim_dt
        gamma_deg = pitch_profile(t, t_meco, t_seco)
        gamma = math.radians(gamma_deg)

        # Thrust / mass flow by phase
        if t < t_meco:
            atm = math.exp(-max(alt, 0.0) / SCALE_HEIGHT_M)
            isp = s1_isp_vac - (s1_isp_vac - s1_isp_sl) * atm
            thrust = s1_thrust * (1.0 - 0.12 * atm)
            mdot = thrust / (isp * G0)
            phase = "stage1_burn"
        elif t < t_sep:
            thrust, mdot = 0.0, 0.0
            phase = "stage_sep"
        elif t < t_ign2:
            if not rows or rows[-1]["flight_phase"] != "stage2_burn":
                # stage 1 drops at separation (once)
                pass
            thrust, mdot = 0.0, 0.0
            phase = "stage_sep"
        elif t < t_seco:
            thrust, mdot = s2_thrust, s2_mdot
            phase = "stage2_burn"
        elif t < t_deploy:
            thrust, mdot = 0.0, 0.0
            phase = "coast"
        elif t < t_deploy + DEPLOY_PHASE_S:
            thrust, mdot = 0.0, 0.0
            phase = "payload_deploy"
        else:
            thrust, mdot = 0.0, 0.0
            phase = "orbit_coast"

        # One-time mass drops
        if t >= t_sep and mass > s2_prop + S2_DRY_KG + PAYLOAD_KG + FAIRING_KG:
            mass = s2_prop + S2_DRY_KG + PAYLOAD_KG + FAIRING_KG
        if not fairing_dropped and alt > 110_000.0:
            mass -= FAIRING_KG
            fairing_dropped = True

        v_air = max(v - wind_bias_mps * math.cos(gamma), 0.0)
        rho = air_density(alt)
        q = 0.5 * rho * v_air * v_air
        max_q = max(max_q, q)
        drag = q * CD * DRAG_AREA_M2 * drag_factor

        g = gravity(alt)
        if t < t_deploy:
            a = (thrust - drag) / mass - g * math.sin(gamma)
        else:
            a = 0.0  # orbital: treat speed as constant post-deploy
        sensed_a = (thrust - drag) / mass if thrust > 0 else drag / mass

        v = max(v + a * sim_dt, 0.0)
        alt = max(alt + v * math.sin(gamma) * sim_dt, 0.0)
        mass = max(mass - mdot * sim_dt, S2_DRY_KG + PAYLOAD_KG)

        if i % sample_every == 0:
            v_inertial = v + EARTH_ROT_MPS * (1.0 - math.sin(gamma))
            rows.append(
                {
                    "time_s": round(t, 1),
                    "altitude_m": round(alt, 1),
                    "inertial_velocity_mps": round(v_inertial, 2),
                    "dynamic_pressure_pa": round(q, 1),
                    "mass_kg": round(mass, 1),
                    "thrust_kn": round(thrust / 1000.0, 2),
                    "acceleration_mps2": round(sensed_a, 3),
                    "flight_path_angle_deg": round(gamma_deg, 3),
                    "flight_phase": phase,
                    "model_name": MODEL_NAME,
                    "sim_number": SIM_NUMBER,
                    "run_number": str(run_number),
                }
            )

    meta = {
        "run_number": run_number,
        "sim_number": SIM_NUMBER,
        "seed": BASE_SEED + run_number,
        "thrust_s1_factor": round(thrust_s1_factor, 5),
        "thrust_s2_factor": round(thrust_s2_factor, 5),
        "isp_factor": round(isp_factor, 5),
        "prop_load_factor": round(prop_load_factor, 5),
        "drag_factor": round(drag_factor, 5),
        "wind_bias_mps": round(wind_bias_mps, 2),
        "t_meco_s": round(t_meco, 2),
        "t_seco_s": round(t_seco, 2),
        "t_deploy_s": round(t_deploy, 2),
        "max_q_pa": round(max_q, 1),
        "final_altitude_m": rows[-1]["altitude_m"],
        "final_inertial_velocity_mps": rows[-1]["inertial_velocity_mps"],
    }
    return rows, meta


def dispersions(run_number: int) -> dict:
    if run_number == 1:
        return dict(
            thrust_s1_factor=1.0,
            thrust_s2_factor=1.0,
            isp_factor=1.0,
            prop_load_factor=1.0,
            drag_factor=1.0,
            wind_bias_mps=0.0,
        )
    rng = np.random.default_rng(BASE_SEED + run_number)
    return dict(
        thrust_s1_factor=float(rng.normal(1.0, 0.02)),
        thrust_s2_factor=float(rng.normal(1.0, 0.02)),
        isp_factor=float(rng.normal(1.0, 0.01)),
        prop_load_factor=float(rng.normal(1.0, 0.01)),
        drag_factor=float(rng.normal(1.0, 0.05)),
        wind_bias_mps=float(rng.normal(0.0, 15.0)),
    )


def main() -> None:
    all_rows: list[dict] = []
    all_meta: list[dict] = []
    for run_number in range(1, NUM_RUNS + 1):
        d = dispersions(run_number)
        rows, meta = simulate_run(run_number, **d)
        all_rows.extend(rows)
        all_meta.append(meta)
        print(
            f"Run {run_number}: MECO {meta['t_meco_s']}s, SECO {meta['t_seco_s']}s, "
            f"deploy {meta['t_deploy_s']}s, max-Q {meta['max_q_pa'] / 1000:.1f} kPa, "
            f"final alt {meta['final_altitude_m'] / 1000:.1f} km, "
            f"v_inertial {meta['final_inertial_velocity_mps'] / 1000:.2f} km/s"
        )

    data_path = OUT_DIR / "ascent_mc_build47.csv"
    with data_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Wrote {len(all_rows)} rows -> {data_path}")

    meta_path = OUT_DIR / "ascent_mc_build47_run_metadata.csv"
    with meta_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_meta[0].keys()))
        writer.writeheader()
        writer.writerows(all_meta)
    print(f"Wrote {len(all_meta)} runs -> {meta_path}")


if __name__ == "__main__":
    main()
