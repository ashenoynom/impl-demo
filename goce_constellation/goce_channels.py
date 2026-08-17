"""Canonical GOCE demo channel namespace.

Raw GOCE replay mnemonics (IHT13026, THT00064, ...) are renamed at
stream time into a hierarchical namespace, `.`-delimited to match the
datasets' prefix_tree_delimiter, shaped as:

    <system>.<subsystem>.<measure>[_<unit>]

Systems: eps (electrical power), tcs (thermal control), aocs (attitude
and orbit control), gnc (guidance/navigation), payload, fsw (flight
software), gse (ground support equipment, ground-test only).

This module is the single source of truth for names: the streamers
rename with CHANNEL_MAP; the workbook/checklist/procedure builders and
goce_limits.py import the constants and groups below. Assignments were
made from the replay's actual value envelopes (2026-08-12).
"""

from __future__ import annotations

# --------------------------------------------------------- raw -> demo map

CHANNEL_MAP: dict[str, str] = {
    # --- EPS: electrical power system ---
    "IHT13050": "eps.bus.voltage_v",                 # 3.76-3.85 V main bus
    "IHT13051": "eps.bus.secondary_voltage_v",       # ~2.45 V
    "IHT13026": "eps.bus.current_a",                 # 1.8-2.9 A main bus load
    "IHT13099": "eps.payload.current_a",             # ~0.20 A payload feed
    "IHT13027": "eps.battery.voltage_v",             # ~11.3 V pack
    "IHT13021": "eps.battery.charge_current_a",      # 0 / 0.107 A trickle
    "IHT13024": "eps.pcdu.ref_voltage_v",            # 1.051 V reference rail
    "IHT13023": "eps.pcdu.total_load_w",             # ~10.9 W
    "IHT13019": "eps.pcdu.fault_flag",               # constant 0 (no fault)
    "IHT13022": "eps.battery.heater_enable",         # constant 0 (off)
    "IHT13098": "eps.solar_array.string_a_voltage_v",  # 3.1-3.7 V
    "IHT13100": "eps.solar_array.string_b_voltage_v",
    "IHT13102": "eps.solar_array.string_c_voltage_v",
    "IHT13101": "eps.feeds.aocs_current_a",          # ~0.20 A subsystem feeds
    "IHT13103": "eps.feeds.comms_current_a",
    "IHT13105": "eps.feeds.obc_current_a",
    "IHT13107": "eps.feeds.gps_current_a",
    # --- TCS: thermal control system ---
    "IHT13029": "tcs.bus.temp_c",                    # ~38 C main bus plate
    "IHT13036": "tcs.bus.battery_temp_c",            # ~29 C
    "IHT13046": "tcs.bus.transponder_temp_c",        # ~32 C
    "IHT13025": "tcs.pcdu.temp_c",                   # ~33.8 C
    "SST00101": "tcs.avionics.gps_temp_c",           # ~23.8 C
    "SST00102": "tcs.avionics.obc_temp_c",           # ~23.1 C
    "SST00103": "tcs.avionics.xband_temp_c",         # ~27.3 C
    "SST00104": "tcs.avionics.sband_temp_c",         # ~26.0 C
    "THT00035": "tcs.structure.panel_xp_temp_c",     # ~23 C
    "THT00036": "tcs.structure.panel_xm_temp_c",     # ~22.7 C
    "THT00048": "tcs.structure.panel_yp_temp_c",     # ~15.9 C
    "THT00064": "tcs.structure.radiator_temp_c",     # ~-25 C radiator
    "THT00069": "tcs.structure.panel_ym_temp_c",     # ~13 C
    "THT00071": "tcs.structure.boom_temp_c",         # ~13.8 C
    "THT00096": "tcs.structure.tank_temp_c",         # ~17 C
    "THT00097": "tcs.structure.panel_zp_temp_c",     # ~18 C
    "THT00098": "tcs.structure.panel_zm_temp_c",     # ~21 C
    "PHT10160": "tcs.solar_panel.wing_a_inner_temp_c",  # 30-34 C
    "PHT10180": "tcs.solar_panel.wing_a_outer_temp_c",
    "PHT10200": "tcs.solar_panel.wing_b_inner_temp_c",
    "PHT10220": "tcs.solar_panel.wing_b_outer_temp_c",
    # --- AOCS: attitude control ---
    "IHT13011": "aocs.rw.wheel_1_speed_rpm",         # 8.6k-15k rpm
    "IHT13012": "aocs.rw.wheel_2_speed_rpm",
    "IHT13013": "aocs.rw.wheel_3_speed_rpm",
    "IHT13014": "aocs.rw.wheel_4_speed_rpm",
    "IHT13135": "aocs.rw.wheel_spare_speed_rpm",
    "AMT00102": "aocs.mag.bx_nt",                    # +/-38k nT
    "AMT00103": "aocs.mag.by_nt",
    "AMT00104": "aocs.mag.bz_nt",
    # --- GNC: orbit / navigation ---
    "SST03263": "gnc.orbit.ecef_x_m",
    "SST03264": "gnc.orbit.ecef_y_m",
    "SST03265": "gnc.orbit.ecef_z_m",
    "SST03266": "gnc.orbit.ecef_vx_ms",
    "SST03267": "gnc.orbit.ecef_vy_ms",
    "SST03268": "gnc.orbit.ecef_vz_ms",
    "SST03269": "gnc.gps.clock_bias_m",              # ~-1.057e6 m
    "SST03270": "gnc.gps.pdop",                      # 1.17-1.30
    # --- payload: gravity gradiometer (GOCE's science instrument) ---
    "CAT35000": "payload.gradiometer.x_ms2",         # ~5e-8 m/s^2
    "CAT35001": "payload.gradiometer.y_ms2",
    "CAT35002": "payload.gradiometer.z_ms2",
}

# Synthetic channels emitted by the streamers (already hierarchical).
GEO_LAT_CHANNEL = "gnc.nav.latitude_deg"
GEO_LON_CHANNEL = "gnc.nav.longitude_deg"
GEO_ALT_CHANNEL = "gnc.nav.altitude_km"
HTR_CHANNEL = "tcs.htr2.duty_cycle_pct"
LOG_CHANNEL = "fsw.event_log"
UPTIME_CHANNEL = "fsw.clock.uptime_s"
BOOT_COUNT_CHANNEL = "fsw.clock.boot_count"

# Ground-test-only channels (TVAC bench).
GSE_CHAMBER_PRESSURE = "gse.tvac.chamber_pressure_torr"
GSE_SHROUD_TEMP = "gse.tvac.shroud_temp_c"
HTR_CMD_COUNT = "tcs.htr2.cmd_count"

# Key story channels, by role.
BUS_VOLTAGE = "eps.bus.voltage_v"
BUS_CURRENT = "eps.bus.current_a"
PAYLOAD_CURRENT = "eps.payload.current_a"
BUS_TEMP = "tcs.bus.temp_c"
PCDU_TEMP = "tcs.pcdu.temp_c"

POSITION_CHANNELS = ["gnc.orbit.ecef_x_m", "gnc.orbit.ecef_y_m", "gnc.orbit.ecef_z_m"]
VELOCITY_CHANNELS = ["gnc.orbit.ecef_vx_ms", "gnc.orbit.ecef_vy_ms", "gnc.orbit.ecef_vz_ms"]

# Ground-station network — rendered as radio-tower custom features on the
# geo panels; matches the procedure's ground-station dropdown.
# (name, latitude_deg, longitude_deg)
GROUND_STATIONS = [
    ("Svalbard", 78.2306, 15.3894),
    ("Troll", -72.0117, 2.5350),
    ("Kiruna", 67.8570, 20.9640),
    ("Wallops", 37.9402, -75.4664),
]

# ------------------------------------------------------- builder groupings

BUS_TEMP_CHANNELS = [
    "tcs.bus.temp_c", "tcs.bus.battery_temp_c", "tcs.bus.transponder_temp_c",
    "tcs.avionics.gps_temp_c", "tcs.avionics.obc_temp_c",
    "tcs.avionics.xband_temp_c", "tcs.avionics.sband_temp_c",
]
STRUCT_TEMP_CHANNELS = [
    "tcs.structure.panel_xp_temp_c", "tcs.structure.panel_xm_temp_c",
    "tcs.structure.panel_yp_temp_c", "tcs.structure.radiator_temp_c",
    "tcs.structure.panel_ym_temp_c", "tcs.structure.boom_temp_c",
    "tcs.structure.tank_temp_c", "tcs.structure.panel_zp_temp_c",
    "tcs.structure.panel_zm_temp_c",
]
PANEL_TEMP_CHANNELS = [
    "tcs.solar_panel.wing_a_inner_temp_c", "tcs.solar_panel.wing_a_outer_temp_c",
    "tcs.solar_panel.wing_b_inner_temp_c", "tcs.solar_panel.wing_b_outer_temp_c",
]
BUS_VOLTAGE_CHANNELS = [
    "eps.bus.voltage_v", "eps.bus.secondary_voltage_v", "eps.battery.voltage_v",
    "eps.solar_array.string_a_voltage_v", "eps.solar_array.string_b_voltage_v",
    "eps.solar_array.string_c_voltage_v",
]
BUS_CURRENT_CHANNELS = [
    "eps.bus.current_a", "eps.payload.current_a", "eps.feeds.aocs_current_a",
    "eps.feeds.comms_current_a", "eps.feeds.obc_current_a",
    "eps.feeds.gps_current_a", "eps.battery.charge_current_a",
]
POWER_RAIL_CHANNELS = ["eps.pcdu.total_load_w", "tcs.pcdu.temp_c", "eps.pcdu.ref_voltage_v"]
WHEEL_CHANNELS = [
    "aocs.rw.wheel_1_speed_rpm", "aocs.rw.wheel_2_speed_rpm",
    "aocs.rw.wheel_3_speed_rpm", "aocs.rw.wheel_4_speed_rpm",
    "aocs.rw.wheel_spare_speed_rpm",
]
ACCEL_CHANNELS = ["payload.gradiometer.x_ms2", "payload.gradiometer.y_ms2", "payload.gradiometer.z_ms2"]
MAG_CHANNELS = ["aocs.mag.bx_nt", "aocs.mag.by_nt", "aocs.mag.bz_nt"]
