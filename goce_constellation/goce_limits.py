"""Canonical GOCE demo limits, fault model, and command-state plumbing.

Single source of truth shared by:
- goce_csv_streamer.py       (fault envelope + variance clamping)
- goce_log_streamer.py       (fault-aware log messages)
- constellation_workbook.py  (fleet status value-table thresholds)
- goce_deepdive_builder.py   (chart redlines + checklist limits)
- goce_runcompare_builder.py (comparison redlines)
- goce_procedure_builder.py  (channel-validation success conditions)
- goce_command_bridge.py     (procedure execution -> fault recovery)

Limits were retuned 2026-08-12 against the actual replay envelope
(sample stats: IHT13026 max 2.90 A, IHT13050 min 3.76 V, IHT13029 max
38.2 degC, IHT13011 max 15,000 rpm) so a healthy fleet reads green and
only a faulted satellite trips warn/alarm bands.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------- limits

# Value-table color tokens: the Nominal frontend expects NAMED tokens
# ("green" / "yellow" / "red"), which theme correctly — not hex strings.
GREEN = "green"
YELLOW = "yellow"
RED = "red"

# Hex equivalents for chart redlines (LineThreshold takes real colors).
HEX_WARN = "#E4A11B"
HEX_ALARM = "#D9534F"

# Ascending (value, color, label) bands: a cell takes the color of the
# highest threshold at or below the live value. "Low is bad" channels
# (bus voltages) start red; everything else starts green and escalates.
# Keys are the hierarchical demo channel names (see goce_channels.py).
CHANNEL_THRESHOLDS: dict[str, list[tuple[float, str, str]]] = {
    # --- EPS (the fault story lives here) ---
    "eps.bus.current_a": [(0, GREEN, "nominal"), (3.00, YELLOW, "high"), (3.15, RED, "overcurrent")],
    "eps.bus.voltage_v": [(0, RED, "undervolt"), (3.60, YELLOW, "low"), (3.68, GREEN, "nominal")],
    "eps.bus.secondary_voltage_v": [(0, RED, "undervolt"), (2.38, YELLOW, "low"), (2.41, GREEN, "nominal")],
    "eps.payload.current_a": [(0, GREEN, "nominal"), (0.30, YELLOW, "high"), (0.35, RED, "overcurrent")],
    "eps.pcdu.total_load_w": [(0, GREEN, "nominal"), (12.0, YELLOW, "high"), (12.6, RED, "alarm")],
    # --- thermal ---
    "tcs.bus.temp_c": [(0, GREEN, "nominal"), (39.0, YELLOW, "warm"), (39.8, RED, "hot")],
    "tcs.bus.battery_temp_c": [(0, GREEN, "nominal"), (30.2, YELLOW, "warm"), (31.2, RED, "hot")],
    "tcs.bus.transponder_temp_c": [(0, GREEN, "nominal"), (33.5, YELLOW, "warm"), (34.5, RED, "hot")],
    "tcs.pcdu.temp_c": [(0, GREEN, "nominal"), (34.8, YELLOW, "high"), (35.5, RED, "alarm")],
    "tcs.avionics.gps_temp_c": [(0, GREEN, "nominal"), (24.6, YELLOW, "warm"), (25.4, RED, "hot")],
    "tcs.structure.radiator_temp_c": [(-100, GREEN, "nominal"), (-24.5, YELLOW, "warm"), (-23.5, RED, "hot")],
    "tcs.solar_panel.wing_a_inner_temp_c": [(0, GREEN, "nominal"), (34.3, YELLOW, "warm"), (35.0, RED, "hot")],
    # --- AOCS ---
    "aocs.rw.wheel_1_speed_rpm": [(0, GREEN, "nominal"), (15200, YELLOW, "high"), (15600, RED, "saturation")],
    # --- heater (synthetic smoking-gun channel; nominal duty ~6-18%) ---
    "tcs.htr2.duty_cycle_pct": [(0, GREEN, "nominal"), (30, YELLOW, "high"), (60, RED, "latched")],
    # --- orbit (geo model breathes 550 +/- 8 km) ---
    "gnc.nav.altitude_km": [(0, RED, "low"), (535, YELLOW, "low"), (540, GREEN, "nominal"),
                            (559.5, YELLOW, "high"), (563, RED, "out of box")],
}

# Checklist / procedure limit constants (same numbers as the red bands
# above — derive both from here so they can't drift apart).
LIMIT_BUS_OVERCURRENT_A = 3.15       # eps.bus.current_a red
LIMIT_BUS_CURRENT_WARN_A = 3.00      # eps.bus.current_a yellow
LIMIT_BUS_UNDERVOLT_V = 3.60         # eps.bus.voltage_v red (below)
LIMIT_BUS_VOLTAGE_WARN_V = 3.68      # eps.bus.voltage_v yellow (below)
LIMIT_BUS_TEMP_HOT_C = 39.8          # tcs.bus.temp_c red
LIMIT_PAYLOAD_OVERCURRENT_A = 0.35   # eps.payload.current_a red
LIMIT_WHEEL_SATURATION_RPM = 15600.0 # aocs.rw.wheel_*_speed_rpm red
LIMIT_RADIATOR_WARM_C = -23.5        # tcs.structure.radiator_temp_c red
LIMIT_PANEL_SUSTAINED_C = 35.0       # tcs.solar_panel.wing_a_inner sustained red
LIMIT_ALT_BOX_LOW_KM = 535.0
LIMIT_ALT_BOX_HIGH_KM = 563.0
# Bus power UDF (P = eps.bus.voltage_v * eps.bus.current_a): median
# ~8.9 W nominal; the replay's load oscillation peaks clamped-nominal
# V x I at ~11.2 W, and the heater fault rides peaks to ~14 W — the
# 12 W budget separates the two envelopes cleanly.
LIMIT_BUS_POWER_BUDGET_W = 12.0

# Stefan-Boltzmann radiator equilibrium UDF:
#   T_eq [K] = (P / (epsilon * sigma * A))^(1/4),  P = V x I
# Calibrated so nominal bus power (~8.9 W) predicts the radiator's
# actual -25 degC equilibrium; at fault power (~12.2 W) the prediction
# jumps to ~-5 degC while the measured radiator stays at -25 degC —
# the ~20 degC deficit IS the heat accumulating in the bus.
STEFAN_BOLTZMANN_W_M2K4 = 5.670e-8
RADIATOR_EMISSIVITY = 0.85
RADIATOR_AREA_M2 = 0.0487
RADIATOR_SIGMA_EPS_A = STEFAN_BOLTZMANN_W_M2K4 * RADIATOR_EMISSIVITY * RADIATOR_AREA_M2
KELVIN_OFFSET_C = -273.15
LIMIT_RADIATOR_EQ_DELTA_C = 8.0   # predicted-minus-measured alarm band
LIMIT_HTR_DUTY_LATCHED_PCT = 60.0    # tcs.htr2.duty_cycle_pct red

# Synthetic heater duty-cycle channel emitted by the streamer for every
# satellite (and present in the ground-test CSV): closed-loop nominal
# duty oscillates 6-18%; the fault pins it to 100%.
from goce_channels import HTR_CHANNEL  # noqa: E402  (single source of truth)

HTR_DUTY_BASE_PCT = 12.0
HTR_DUTY_SWING_PCT = 6.0
HTR_DUTY_PERIOD_S = 1800.0  # simulated seconds per duty oscillation


def htr_duty_nominal(elapsed_sim_seconds: float, satellite_id: int) -> float:
    """Closed-loop heater duty in percent (6-18%, per-sat phase offset)."""
    import math
    return HTR_DUTY_BASE_PCT + HTR_DUTY_SWING_PCT * math.sin(
        2.0 * math.pi * elapsed_sim_seconds / HTR_DUTY_PERIOD_S + satellite_id
    )


def htr_duty_with_fault(elapsed_sim_seconds: float, satellite_id: int, envelope: float) -> float:
    """Heater duty including the latch fault: pinned toward 100% as the
    fault envelope rises."""
    base = htr_duty_nominal(elapsed_sim_seconds, satellite_id)
    return base + (100.0 - base) * max(0.0, min(1.0, envelope))

# Channels whose limits are monitored fleet-wide: per-satellite variance
# is clamped tight on these so a healthy fleet never wanders across a
# warn band (EPS telemetry on identical buses is tightly controlled).
MONITORED_CHANNELS = set(CHANNEL_THRESHOLDS) - {"gnc.nav.altitude_km"}
MONITORED_GAIN_RANGE = 0.010    # +/-1.0% fixed gain on monitored channels
MONITORED_DRIFT_AMPLITUDE = 0.004  # +/-0.4% slow drift

# The 72h GOCE replay is *anomalous by construction* — it embeds native
# excursions (bus temp to 58 C, bus voltage sags to 2.9 V, wheels to
# 21k rpm) that every satellite replays at shifted offsets. To keep the
# fleet board deterministically green except for the injected fault,
# monitored channels are clamped into their nominal band at stream time
# (fault deltas are added AFTER the clamp, so only the commanded fault
# crosses a limit). Bands chosen so clamp * (1 + variance 1.5%) stays
# inside the green band of CHANNEL_THRESHOLDS above.
NOMINAL_CLAMPS: dict[str, tuple[float | None, float | None]] = {
    "eps.bus.current_a": (None, 2.92),
    "eps.bus.voltage_v": (3.74, None),
    "eps.payload.current_a": (None, 0.285),
    "eps.pcdu.total_load_w": (None, 11.8),
    "tcs.bus.temp_c": (None, 38.7),
    "tcs.bus.battery_temp_c": (None, 29.9),
    "tcs.bus.transponder_temp_c": (None, 33.3),
    "tcs.pcdu.temp_c": (None, 34.4),
    "tcs.avionics.gps_temp_c": (None, 24.4),
    "tcs.solar_panel.wing_a_inner_temp_c": (None, 34.1),
    "aocs.rw.wheel_1_speed_rpm": (None, 14800.0),
    "aocs.rw.wheel_2_speed_rpm": (None, 14800.0),
    "aocs.rw.wheel_3_speed_rpm": (None, 14800.0),
    "aocs.rw.wheel_4_speed_rpm": (None, 14800.0),
    "aocs.rw.wheel_spare_speed_rpm": (None, 14800.0),
}


def clamp_nominal(channels: dict) -> dict:
    """Clamp monitored channels into their nominal band, in place."""
    for ch, (lo, hi) in NOMINAL_CLAMPS.items():
        v = channels.get(ch)
        if v is None:
            continue
        if lo is not None and v < lo:
            channels[ch] = lo
        elif hi is not None and v > hi:
            channels[ch] = hi
    return channels

# ------------------------------------------------------------ fault model

# The demo fault: GOCE-7's payload heater HTR-2 controller latches at
# 100% duty. Constant extra load -> bus current up, bus voltage sags,
# bus temperature climbs. Cleared by the HTR2_PWR_CYCLE command.
FAULT_SATELLITE = "GOCE-7"
FAULT_ID = "htr2_runaway"
COMMAND_NAME = "HTR2_PWR_CYCLE"

# Additive deltas at full fault (envelope f in [0, 1] scales them).
FAULT_DELTAS: dict[str, float] = {
    "eps.bus.current_a": +1.00,     # 2.35 -> 3.35 median (red > 3.15)
    "eps.bus.voltage_v": -0.25,     # 3.80 -> 3.55 (red < 3.60)
    "eps.payload.current_a": +0.22, # 0.20 -> 0.42 (red > 0.35)
    "tcs.bus.temp_c": +2.80,        # 38.0 -> 40.8 (red > 39.8)
    "tcs.pcdu.temp_c": +0.90,       # 33.8 -> 34.7 (yellow, corroborating)
}

FAULT_RAMP_S = 120.0     # wall seconds from arm to full fault (thermal-ish ramp)
RECOVERY_TAU_S = 45.0    # wall-clock exponential recovery time constant
RECOVERY_DONE_S = 240.0  # envelope treated as 0 after this long recovering

# ---------------------------------------------------------- command state

COMMAND_STATE_PATH = SCRIPT_DIR / "command_state.json"

NOMINAL_STATE = {"state": "nominal", "fault": None, "t_armed": None, "t_recovery": None}


def read_command_state(path: Path = COMMAND_STATE_PATH) -> Dict:
    """Read the command-state file; missing/corrupt file == nominal."""
    try:
        with open(path) as f:
            data = json.load(f)
        sat = data.get(FAULT_SATELLITE) or {}
        return {**NOMINAL_STATE, **sat}
    except (OSError, json.JSONDecodeError, ValueError):
        return dict(NOMINAL_STATE)


def write_command_state(
    state: str,
    t_armed: Optional[float] = None,
    t_recovery: Optional[float] = None,
    source: str = "manual",
    path: Path = COMMAND_STATE_PATH,
) -> Dict:
    """Write the command-state file atomically (tmp + rename)."""
    payload = {
        FAULT_SATELLITE: {
            "state": state,
            "fault": FAULT_ID if state != "nominal" else None,
            "t_armed": t_armed,
            "t_recovery": t_recovery,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
        }
    }
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)
    return payload[FAULT_SATELLITE]


def fault_envelope(state: Dict, now: Optional[float] = None) -> float:
    """Fault envelope f in [0, 1] from a command-state dict.

    armed/active: ramps 0 -> 1 over FAULT_RAMP_S from t_armed.
    recovering:   exponential decay from the level at t_recovery.
    nominal:      0.
    """
    now = time.time() if now is None else now
    s = state.get("state", "nominal")
    t_armed = state.get("t_armed")
    t_recovery = state.get("t_recovery")

    def ramp(t0: float, t: float) -> float:
        if t <= t0:
            return 0.0
        return min(1.0, (t - t0) / FAULT_RAMP_S)

    if s in ("armed", "active") and t_armed is not None:
        return ramp(float(t_armed), now)
    if s == "recovering" and t_recovery is not None:
        t_rec = float(t_recovery)
        level_at_recovery = ramp(float(t_armed), t_rec) if t_armed is not None else 1.0
        dt = max(0.0, now - t_rec)
        if dt >= RECOVERY_DONE_S:
            return 0.0
        return level_at_recovery * pow(2.718281828, -dt / RECOVERY_TAU_S)
    return 0.0


class FaultManager:
    """Cheap polling wrapper: re-reads command_state.json at most every
    poll_interval seconds (checked inline from the streaming hot loop)."""

    def __init__(self, path: Path = COMMAND_STATE_PATH, poll_interval: float = 2.0):
        self.path = path
        self.poll_interval = poll_interval
        self._state = read_command_state(path)
        self._last_poll = 0.0

    def state(self) -> Dict:
        now = time.time()
        if now - self._last_poll >= self.poll_interval:
            self._state = read_command_state(self.path)
            self._last_poll = now
        return self._state

    def envelope(self, satellite_tag: str) -> float:
        """Current fault envelope for one satellite (0 for all but the
        fault satellite)."""
        if satellite_tag != FAULT_SATELLITE:
            return 0.0
        return fault_envelope(self.state())

    def apply(self, satellite_tag: str, channels: Dict[str, float]) -> float:
        """Apply the fault deltas in place; returns the envelope used."""
        f = self.envelope(satellite_tag)
        if f > 0.0:
            for ch, delta in FAULT_DELTAS.items():
                if ch in channels:
                    channels[ch] += delta * f
        return f
