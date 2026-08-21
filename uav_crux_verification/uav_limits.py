"""Single source of truth for the UAV verification demo's data model.

For every Crux requirement that gets an automated check, this file defines:
- the violation triggers (channel, operator, threshold) that become the Crux
  check tree AND the published Core checklist condition, and
- the streamer's nominal band for each channel, chosen so nominal noise can
  NEVER cross a trigger (margin >= ~30%), and
- the fault excursion used by the failure track.

Channel namespace is hierarchical per subsystem (fcs.*, nav.*, prp.*, pwr.*,
pay.*, dl.*, plus component prefixes) — the GOCE lesson: hierarchical names
render as a browsable tree in the app. flt.* channels are context-only.
"""

from __future__ import annotations

# channel -> (unit, base, amplitude). The streamer holds each channel at
# base ± amplitude (noise + slow drift); scenario windows sweep within the
# same band unless a fault is armed.
CHANNELS: dict[str, tuple[str, float, float]] = {
    # context / flight state
    "flt.altitude_m": ("m", 1200.0, 150.0),
    "flt.airspeed_kts": ("kts", 95.0, 10.0),
    "flt.roll_deg": ("deg", 0.0, 8.0),
    "flt.pitch_deg": ("deg", 2.0, 3.0),
    # flight control subsystem + components
    "fcs.att_err_deg": ("deg", 1.0, 0.6),
    "fcs.roll_rate_dps": ("deg/s", 12.0, 6.0),
    "fcs.recovery_time_s": ("s", 1.8, 0.5),
    "fcs.ice_index": ("", 0.15, 0.10),
    "ahrs.false_alarm_per_hr": ("1/h", 0.30, 0.20),
    "ahrs.range_err_m": ("m", 1.8, 0.8),
    "fcc.range_err_m": ("m", 2.0, 0.9),
    "fcc.latency_ms": ("ms", 14.0, 4.0),
    "adp.latency_ms": ("ms", 11.0, 4.0),
    "adp.health_pct": ("%", 96.0, 2.5),
    # navigation
    "nav.drift_m_per_km": ("m/km", 4.0, 1.5),
    "nav.cep_m": ("m", 2.5, 1.0),
    "ins.false_alarm_per_hr": ("1/h", 0.30, 0.20),
    "ins.range_err_m": ("m", 1.9, 0.8),
    "gnss.range_err_m": ("m", 1.7, 0.8),
    "gnss.latency_ms": ("ms", 10.0, 4.0),
    # propulsion / power
    "prp.endurance_hr": ("h", 20.5, 1.0),
    "prp.restart_time_s": ("s", 4.5, 1.5),
    "eng.false_alarm_per_hr": ("1/h", 0.30, 0.20),
    "str.range_err_m": ("m", 1.6, 0.8),
    "str.latency_ms": ("ms", 9.0, 4.0),
    "pwr.margin_pct": ("%", 28.0, 2.5),
    "gen.false_alarm_per_hr": ("1/h", 0.30, 0.20),
    "gen.range_err_m": ("m", 1.5, 0.7),
    # payload / detect-and-avoid
    "pay.detect_range_km": ("km", 3.2, 0.5),
    "pay.track_confidence_pct": ("%", 95.0, 3.0),
    "pay.eoir_detect_km": ("km", 4.2, 0.6),
    "daa.false_alarm_per_hr": ("1/h", 0.25, 0.20),
    # datalink
    "dl.link_margin_db": ("dB", 8.0, 2.5),
    "dl.rtb_response_s": ("s", 3.0, 1.0),
    "sat.false_alarm_per_hr": ("1/h", 0.30, 0.20),
    "sat.range_err_m": ("m", 1.8, 0.8),
}

# requirement external id -> violation triggers. Each trigger is
# (channel, operator, threshold); the check tree ORs them (mode "any"):
# any trigger firing during the run window fails the run.
REQUIREMENT_TRIGGERS: dict[str, list[tuple[str, str, float]]] = {
    # ── Tree 1: SYS-REQ-001 flight stability ────────────────────────────
    "SYS-REQ-001": [("fcs.att_err_deg", ">", 5.0), ("fcs.roll_rate_dps", ">", 30.0)],
    "FCS-REQ-001": [("fcs.att_err_deg", ">", 2.5)],
    "FCS-REQ-002": [("fcs.recovery_time_s", ">", 3.0)],
    "FCS-REQ-003": [("fcs.ice_index", ">", 0.8)],
    "AHRS-REQ-001": [("ahrs.false_alarm_per_hr", ">", 1.0)],
    "AHRS-REQ-002": [("ahrs.range_err_m", ">", 5.0)],
    "FCC-REQ-001": [("fcc.range_err_m", ">", 5.0)],
    "FCC-REQ-002": [("fcc.latency_ms", ">", 25.0)],
    "ADP-REQ-001": [("adp.latency_ms", ">", 20.0)],
    "ADP-REQ-002": [("adp.health_pct", "<", 85.0)],
    # ── Tree 2: SYS-REQ-002 GPS-denied navigation ───────────────────────
    "SYS-REQ-002": [("nav.cep_m", ">", 8.0), ("nav.drift_m_per_km", ">", 10.0)],
    "NAV-REQ-001": [("nav.drift_m_per_km", ">", 8.0)],
    "NAV-REQ-002": [("nav.cep_m", ">", 5.0)],
    "INS-REQ-001": [("ins.false_alarm_per_hr", ">", 1.0)],
    "INS-REQ-002": [("ins.range_err_m", ">", 5.0)],
    "GNSS-REQ-001": [("gnss.range_err_m", ">", 5.0)],
    "GNSS-REQ-002": [("gnss.latency_ms", ">", 20.0)],
    # ── Tree 3: SYS-REQ-003 endurance & power ───────────────────────────
    "SYS-REQ-003": [("prp.endurance_hr", "<", 18.0), ("pwr.margin_pct", "<", 15.0)],
    "PRP-REQ-001": [("prp.endurance_hr", "<", 18.0)],
    "PRP-REQ-002": [("prp.restart_time_s", ">", 10.0)],
    "ENG-REQ-001": [("eng.false_alarm_per_hr", ">", 1.0)],
    "STR-REQ-001": [("str.range_err_m", ">", 5.0)],
    "STR-REQ-002": [("str.latency_ms", ">", 20.0)],
    "PWR-REQ-001": [("pwr.margin_pct", "<", 20.0)],
    "GEN-REQ-001": [("gen.false_alarm_per_hr", ">", 1.0)],
    "GEN-REQ-002": [("gen.range_err_m", ">", 5.0)],
    # ── Tree 4: SYS-REQ-004 detect & avoid ──────────────────────────────
    "SYS-REQ-004": [("pay.detect_range_km", "<", 1.5), ("pay.track_confidence_pct", "<", 85.0)],
    "PAY-REQ-001": [("pay.detect_range_km", "<", 2.0)],
    "PAY-REQ-002": [("pay.eoir_detect_km", "<", 3.0)],
    "DAA-REQ-001": [("daa.false_alarm_per_hr", ">", 1.0)],
    # ── Tree 5: SYS-REQ-005 C2 datalink ─────────────────────────────────
    "SYS-REQ-005": [("dl.link_margin_db", "<", 3.0), ("dl.rtb_response_s", ">", 5.0)],
    "DL-REQ-001": [("dl.link_margin_db", "<", 3.0)],
    "DL-REQ-002": [("dl.rtb_response_s", ">", 5.0)],
    "SAT-REQ-001": [("sat.false_alarm_per_hr", ">", 1.0)],
    "SAT-REQ-002": [("sat.range_err_m", ">", 5.0)],
    "FCC-REQ-003": [("fcc.range_err_m", ">", 5.0)],
}

# The failure track: requirement whose scenario the fault injector poisons.
FAULT_REQUIREMENT = "PWR-REQ-001"

# Scenario window: how long a commanded test-case window streams before the
# run is bounded and the checklist executes.
SCENARIO_WINDOW_S = 45.0


def unit_of(channel: str) -> str:
    return CHANNELS[channel][0]


def fault_value(channel: str, operator: str, threshold: float) -> float:
    """A value decisively past the trigger for the failure track."""
    span = max(abs(threshold) * 0.4, 1.0)
    return threshold + span if operator in (">", ">=") else threshold - span


def check_tree(ext_id: str) -> dict:
    """Crux Lite RequirementCheck tree (violation triggers, OR'd)."""
    rows = [
        {
            "kind": "value",
            "channel": channel,
            "operator": op,
            "threshold": threshold,
            **({"unit": unit_of(channel)} if unit_of(channel) else {}),
        }
        for channel, op, threshold in REQUIREMENT_TRIGGERS[ext_id]
    ]
    return {"mode": "any", "items": rows}


def nominal_bounds(channel: str) -> tuple[float, float]:
    _, base, amp = CHANNELS[channel]
    return base - amp, base + amp
