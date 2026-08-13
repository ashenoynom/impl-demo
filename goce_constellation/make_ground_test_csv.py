#!/usr/bin/env python3
"""Generate the GOCE-7 EPS TVAC ground-test CSV for run comparison RCA.

Recreates the HTR-2 heater-controller latch-up observed during the FM
thermal-vacuum campaign (2026-03-14): heater duty pins at 100%, bus
current steps up ~1 A, bus voltage sags ~0.25 V, bus temperature climbs
~2.8 degC — the exact signature the flight fault model injects (deltas
come from goce_limits.FAULT_DELTAS, so flight and ground can't drift
apart). An HTR2_PWR_CYCLE command at T+120 min breaks the latch and the
bus recovers.

Timeline (3 h at 1 Hz bench instrumentation):
    T+0     nominal closed-loop heater control
    T+45m   latch event: duty -> 100%, EPS signature ramps in (~20 min)
    T+120m  HTR2_PWR_CYCLE command -> exponential recovery (tau 8 min)
    T+150m  back to nominal, hold to T+180m

Output: data/goce7_eps_tvac_ground_test.csv (channels use the same
names as flight telemetry, plus TVAC context channels).
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from goce_channels import (
    GSE_CHAMBER_PRESSURE,
    GSE_SHROUD_TEMP,
    HTR_CHANNEL,
    HTR_CMD_COUNT,
)
from goce_limits import FAULT_DELTAS, htr_duty_nominal

OUT_PATH = Path(__file__).resolve().parent / "data" / "goce7_eps_tvac_ground_test.csv"

START = datetime(2026, 3, 14, 8, 0, 0, tzinfo=timezone.utc)
DURATION_S = 3 * 3600
LATCH_S = 45 * 60
CMD_S = 120 * 60
FAULT_RAMP_S = 20 * 60      # TVAC thermal mass: slower ramp than flight wall-clock
RECOVERY_TAU_S = 8 * 60

# Bench-nominal base values (bench PSU is steadier than orbit: small
# noise, slow drift, no orbital oscillation). Bases match the flight
# replay medians so overlays line up. Keys are the hierarchical demo
# channel names — identical to what flight telemetry streams.
BASES = {
    "eps.bus.current_a": (2.35, 0.030),         # (base, noise sigma)
    "eps.bus.voltage_v": (3.80, 0.006),
    "eps.bus.secondary_voltage_v": (2.45, 0.004),
    "eps.payload.current_a": (0.20, 0.010),
    "tcs.bus.temp_c": (38.0, 0.060),
    "tcs.bus.battery_temp_c": (29.2, 0.050),
    "tcs.pcdu.temp_c": (33.8, 0.060),
    "eps.pcdu.total_load_w": (10.9, 0.100),
    "tcs.avionics.gps_temp_c": (23.8, 0.040),
}


def envelope(t: float) -> float:
    """Ground-test fault envelope f(t) in [0, 1]."""
    if t < LATCH_S:
        return 0.0
    if t < CMD_S:
        return min(1.0, (t - LATCH_S) / FAULT_RAMP_S)
    return math.exp(-(t - CMD_S) / RECOVERY_TAU_S)


def main() -> None:
    rng = random.Random("goce7-tvac-2026-03-14")
    rows = []
    for t in range(0, DURATION_S):
        f = envelope(t)
        row = {"timestamp": (START + timedelta(seconds=t)).isoformat()}
        for ch, (base, sigma) in BASES.items():
            slow = 0.15 * sigma * math.sin(2 * math.pi * t / 1500.0)
            value = base + rng.gauss(0.0, sigma) + slow
            value += FAULT_DELTAS.get(ch, 0.0) * f
            row[ch] = round(value, 5)

        # Heater duty: closed-loop nominal, pinned at 100% while latched
        # (duty is pinned the instant the latch happens — it does not
        # ramp with the thermal signature), restored after the command.
        duty = htr_duty_nominal(float(t), satellite_id=7)
        if LATCH_S <= t < CMD_S:
            duty = 100.0
        elif t >= CMD_S:
            duty = duty + (100.0 - duty) * math.exp(-(t - CMD_S) / 90.0)
        row[HTR_CHANNEL] = round(duty + rng.gauss(0.0, 0.15), 3)

        # TVAC context channels (gse.* namespace, ground-test only)
        row[GSE_CHAMBER_PRESSURE] = round(2.1e-6 * (1 + rng.gauss(0, 0.02)), 10)
        row[GSE_SHROUD_TEMP] = round(45.0 + 0.4 * math.sin(2 * math.pi * t / 2400.0) + rng.gauss(0, 0.05), 4)
        row[HTR_CMD_COUNT] = 12 + (1 if t >= LATCH_S else 0) + (1 if t >= CMD_S else 0)
        rows.append(row)

    df = pd.DataFrame(rows)
    OUT_PATH.parent.mkdir(exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(df)} rows x {len(df.columns)} cols -> {OUT_PATH}")
    for ch in ("eps.bus.current_a", "eps.bus.voltage_v", "tcs.bus.temp_c", HTR_CHANNEL):
        s = df[ch]
        print(f"  {ch}: min={s.min():.3f} median={s.median():.3f} max={s.max():.3f}")


if __name__ == "__main__":
    main()
