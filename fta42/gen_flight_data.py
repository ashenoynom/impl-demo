#!/usr/bin/env python3
"""Generate a simulated generic fixed-wing flight-test dataset.

Entirely synthetic — no customer data. Profile: taxi, takeoff, climb to
8,500 ft, a flight-test block (doublets, steady-heading sideslips, bank
sweeps, accel/decel run) flown in a racetrack near Mojave, then descent
and landing. 10 Hz, ~45 minutes.
"""
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
HZ = 10
DUR_S = 2700  # 45 min
N = DUR_S * HZ
t = np.arange(N) / HZ  # seconds from brake release - 180

# Flight starts 2026-07-21 16:00:00 UTC
T0 = pd.Timestamp("2026-07-21T16:00:00Z")
timestamps = T0 + pd.to_timedelta(t, unit="s")

# ---------------------------------------------------------------- phases
# 0-180 taxi | 180-240 TO roll+rotate | 240-720 climb | 720-2280 test block
# 2280-2580 descent | 2580-2660 approach | 2660-2700 rollout
def smooth(x, w):
    k = int(w * HZ)
    if k < 2:
        return x
    kern = np.hanning(k); kern /= kern.sum()
    xp = np.pad(x, k, mode="edge")  # avoid zero-padding edge artifacts
    return np.convolve(xp, kern, mode="same")[k:-k]

def seg(t, pts):
    """Piecewise-linear interpolation through (time, value) points."""
    tt = np.array([p[0] for p in pts], dtype=float)
    vv = np.array([p[1] for p in pts], dtype=float)
    return np.interp(t, tt, vv)

noise = lambda s: RNG.normal(0, s, N)

# ---------------------------------------------------------------- airspeed / altitude
ias = seg(t, [(0, 0), (30, 8), (170, 12), (180, 0), (185, 20), (215, 75),
              (240, 95), (480, 110), (720, 130),
              (1400, 130), (1450, 165), (1550, 165), (1600, 130),  # accel/decel run
              (2280, 130), (2400, 120), (2580, 90), (2650, 68), (2665, 55), (2680, 20), (2700, 5)])
ias = smooth(ias, 8) + noise(0.6)
ias = np.clip(ias, 0, None)

alt = seg(t, [(0, 2790), (240, 2790), (300, 3400), (720, 8500),
              (2280, 8500), (2580, 3800), (2660, 2810), (2680, 2790), (2700, 2790)])
alt = smooth(alt, 15) + noise(3.0)

vspd = np.gradient(alt, 1.0 / HZ) * 60.0  # fpm
vspd = smooth(vspd, 6) + noise(15)

radalt = np.clip(alt - 2790 + noise(2.0), 0, 2500)  # field elev 2790 MSL
oat = 32.0 - 1.98 * (alt - 2790) / 1000.0 + noise(0.15)  # deg C
tas = ias * (1 + 0.015 * (alt - 2790) / 1000.0)
mach = tas / (661.5 * np.sqrt((oat + 273.15) / 288.15))
static_p = 14.696 * (1 - 6.8756e-6 * alt) ** 5.2559  # psi

# ---------------------------------------------------------------- test points
tp_windows = [
    (780, 840,  "TP-01 Trim Shot 130 KIAS"),
    (900, 960,  "TP-02 Pitch Doublet"),
    (1020, 1080, "TP-03 Roll Doublet"),
    (1140, 1200, "TP-04 Rudder Doublet"),
    (1260, 1360, "TP-05 Steady Heading Sideslip"),
    (1400, 1600, "TP-06 Level Accel/Decel"),
    (1680, 1860, "TP-07 Bank Sweep 30/45/60"),
    (1920, 2040, "TP-08 Phugoid"),
    (2100, 2220, "TP-09 Stall Approach (clean)"),
]
test_point = np.array(["CRUISE"] * N, dtype=object)
test_active = np.zeros(N)
for (a, b, label) in tp_windows:
    m = (t >= a) & (t < b)
    test_point[m] = label
    test_active[m] = 1
test_point[t < 180] = "GROUND OPS"
test_point[(t >= 180) & (t < 300)] = "TAKEOFF"
test_point[(t >= 300) & (t < 720)] = "CLIMB"
test_point[(t >= 2280) & (t < 2580)] = "DESCENT"
test_point[t >= 2580] = "APPROACH/LAND"

def doublet(t, t0, period, amp):
    """One cycle doublet starting at t0."""
    x = np.zeros_like(t)
    m1 = (t >= t0) & (t < t0 + period / 2)
    m2 = (t >= t0 + period / 2) & (t < t0 + period)
    x[m1] = amp; x[m2] = -amp
    return x

# ---------------------------------------------------------------- attitude
pitch = seg(t, [(0, 0.5), (180, 0.5), (188, 12), (300, 10), (720, 6),
                (2280, 2), (2400, -3), (2580, -2.5), (2660, 4), (2668, 1), (2700, 0.5)])
pitch += doublet(t, 905, 8, 4) + doublet(t, 1925, 40, 3)          # pitch doublet + phugoid
pitch += np.where((t >= 2100) & (t < 2220), seg(t, [(2100, 0), (2190, 9), (2205, -6), (2220, 0)]), 0)
pitch = smooth(pitch, 3) + noise(0.08)

# racetrack: two 180-deg turns per lap in the test block
heading = seg(t, [(0, 120), (60, 300), (170, 120), (180, 120), (240, 120), (720, 120)] +
                 [(720 + i * 390, 120 + (i % 2) * 180) for i in range(5)] +
                 [(2280, 300), (2450, 120), (2580, 120), (2700, 120)])
heading = (smooth(heading, 10) + noise(0.2)) % 360

roll = np.gradient(seg(t, [(p, h) for p, h in zip(t[::HZ * 30], heading[::HZ * 30])]), 1.0 / HZ)
roll = np.clip(smooth(roll * 8, 12), -45, 45)
roll += doublet(t, 1025, 6, 15)                                    # roll doublet
bank_sweep = np.where((t >= 1680) & (t < 1740), 30, 0) + \
             np.where((t >= 1740) & (t < 1800), 45, 0) + \
             np.where((t >= 1800) & (t < 1860), 60, 0)
roll += smooth(bank_sweep, 8)
roll = smooth(roll, 2) + noise(0.15)

aoa = np.clip(2.0 + (130 - ias) * 0.09 + pitch * 0.15, -2, 16) + noise(0.1)
aoa[t < 180] = 0.3 + noise(0.05)[t < 180]
beta = doublet(t, 1145, 10, 6) + np.where((t >= 1260) & (t < 1360),
        seg(t, [(1260, 0), (1280, 8), (1330, -8), (1360, 0)]), 0)
beta = smooth(beta, 3) + noise(0.15)

p_rate = np.gradient(roll, 1.0 / HZ);  p_rate = smooth(p_rate, 1) + noise(0.3)
q_rate = np.gradient(pitch, 1.0 / HZ); q_rate = smooth(q_rate, 1) + noise(0.3)
r_rate = np.gradient(np.unwrap(np.deg2rad(heading)) * 57.2958, 1.0 / HZ)
r_rate = smooth(np.clip(r_rate, -20, 20), 2) + noise(0.2)

nz = 1.0 / np.clip(np.cos(np.deg2rad(np.clip(roll, -60, 60))), 0.5, 1.0)
nz += q_rate * 0.02 + noise(0.02)
nz[t < 180] = 1.0 + noise(0.01)[t < 180]
nx = np.gradient(smooth(tas, 5), 1.0 / HZ) * 0.0526 + noise(0.01)  # kts/s -> g
ny = beta * 0.02 + noise(0.008)

# ---------------------------------------------------------------- controls & actuators
elevator = -pitch * 0.6 - 1.2 + doublet(t, 905, 8, 6) + noise(0.12)
aileron_l = roll * 0.25 + doublet(t, 1025, 6, 9) + noise(0.12)
aileron_r = -aileron_l + noise(0.08)
rudder = beta * 0.8 + doublet(t, 1145, 10, 8) + noise(0.12)
flap = seg(t, [(0, 0), (175, 10), (330, 0), (2560, 0), (2575, 10), (2620, 25), (2700, 25)])
trim = smooth(-elevator * 0.35, 30) + noise(0.03)

def act_current(surface_rate, base=0.8):
    return np.clip(base + np.abs(surface_rate) * 0.35, 0, 12) + noise(0.05)

elev_cur = act_current(np.gradient(elevator, 1.0 / HZ))
ail_l_cur = act_current(np.gradient(aileron_l, 1.0 / HZ))
ail_r_cur = act_current(np.gradient(aileron_r, 1.0 / HZ))
rud_cur = act_current(np.gradient(rudder, 1.0 / HZ))

def act_temp(cur, amb):
    tmp = np.empty(N); v = amb[0] + 5
    for i in range(N):
        v += (0.9 * cur[i] - (v - amb[i]) * 0.012) / HZ
        tmp[i] = v
    return tmp + RNG.normal(0, 0.05, N)

elev_tmp = act_temp(elev_cur, oat); ail_l_tmp = act_temp(ail_l_cur, oat)
ail_r_tmp = act_temp(ail_r_cur, oat); rud_tmp = act_temp(rud_cur, oat)

# ---------------------------------------------------------------- engine
throttle = seg(t, [(0, 12), (170, 15), (180, 98), (300, 92), (720, 75),
                   (1400, 75), (1430, 100), (1550, 100), (1580, 55), (1620, 75),
                   (2280, 40), (2580, 30), (2660, 12), (2700, 8)])
throttle = smooth(throttle, 6) + noise(0.3)
rpm = 750 + throttle * 24.5 + noise(8)
man_p = 10 + throttle * 0.19 - (alt - 2790) * 2.2e-4
fuel_flow = np.clip(1.2 + throttle * 0.165, 0.8, 20) + noise(0.05)
fuel_qty = 74.0 - np.cumsum(fuel_flow) / (3600.0 * HZ)
egt = smooth(620 + throttle * 2.1, 20) + noise(2.0)
cht = smooth(95 + throttle * 0.85, 60) + noise(0.5)
oil_t = smooth(60 + throttle * 0.35, 90) + noise(0.2)
oil_p = np.clip(smooth(28 + rpm * 0.011, 10), 25, 95) + noise(0.4)

# ---------------------------------------------------------------- electrical
bus_v = 27.8 + noise(0.05) - (elev_cur + ail_l_cur + ail_r_cur + rud_cur) * 0.01
bus_a = 22 + (elev_cur + ail_l_cur + ail_r_cur + rud_cur) + noise(0.4)
batt_v = 25.1 + noise(0.03)
batt_t = smooth(28 + bus_a * 0.08, 120) + noise(0.1)

# ---------------------------------------------------------------- GPS track
gs = np.clip(tas + 8 * np.cos(np.deg2rad(heading - 250)), 0, None)  # wind 250/8
gs[t < 180] = ias[t < 180]
lat = np.empty(N); lon = np.empty(N)
lat[0], lon[0] = 35.0592, -118.1520  # Mojave-ish ramp
for i in range(1, N):
    d = gs[i] * 0.514444 / HZ  # m per sample
    lat[i] = lat[i - 1] + d * np.cos(np.deg2rad(heading[i])) / 111_111.0
    lon[i] = lon[i - 1] + d * np.sin(np.deg2rad(heading[i])) / (111_111.0 * np.cos(np.deg2rad(lat[i - 1])))
num_sats = np.clip(11 + RNG.integers(-1, 2, N), 8, 14)

# ---------------------------------------------------------------- assemble
df = pd.DataFrame({
    "timestamp": timestamps.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3] + "Z",
    "flight.ias_kts": ias, "flight.tas_kts": tas, "flight.altitude_ft": alt,
    "flight.radalt_ft": radalt, "flight.vspeed_fpm": vspd, "flight.mach": mach,
    "attitude.roll_deg": roll, "attitude.pitch_deg": pitch, "attitude.heading_deg": heading,
    "attitude.aoa_deg": aoa, "attitude.beta_deg": beta,
    "rates.p_dps": p_rate, "rates.q_dps": q_rate, "rates.r_dps": r_rate,
    "accel.nx_g": nx, "accel.ny_g": ny, "accel.nz_g": nz,
    "controls.elevator_deg": elevator, "controls.aileron_l_deg": aileron_l,
    "controls.aileron_r_deg": aileron_r, "controls.rudder_deg": rudder,
    "controls.flap_deg": flap, "controls.stab_trim_deg": trim,
    "actuators.elev_current_a": elev_cur, "actuators.ail_l_current_a": ail_l_cur,
    "actuators.ail_r_current_a": ail_r_cur, "actuators.rud_current_a": rud_cur,
    "actuators.elev_temp_c": elev_tmp, "actuators.ail_l_temp_c": ail_l_tmp,
    "actuators.ail_r_temp_c": ail_r_tmp, "actuators.rud_temp_c": rud_tmp,
    "engine.rpm": rpm, "engine.egt_c": egt, "engine.cht_c": cht,
    "engine.oil_press_psi": oil_p, "engine.oil_temp_c": oil_t,
    "engine.fuel_flow_gph": fuel_flow, "engine.fuel_qty_gal": fuel_qty,
    "engine.throttle_pct": throttle, "engine.manifold_press_inhg": man_p,
    "elec.bus_volts": bus_v, "elec.bus_amps": bus_a,
    "elec.batt_volts": batt_v, "elec.batt_temp_c": batt_t,
    "gps.latitude_deg": lat, "gps.longitude_deg": lon,
    "gps.ground_speed_kts": gs, "gps.track_deg": heading,
    "gps.num_sats": num_sats,
    "env.oat_c": oat, "env.static_press_psi": static_p,
    "test.test_point": test_point, "test.test_active": test_active,
})
num_cols = [c for c in df.columns if c not in ("timestamp", "test.test_point")]
df[num_cols] = df[num_cols].round(4)
out = __file__.rsplit("/", 1)[0] + "/fta42_flight04.csv"
df.to_csv(out, index=False)
print(f"wrote {out}: {len(df)} rows x {len(df.columns)} cols")
print(df[["flight.ias_kts", "flight.altitude_ft", "attitude.roll_deg", "gps.latitude_deg"]].describe().to_string())
