#!/usr/bin/env python3
"""Stream live simulated FTA-42 flight data into the demo-tenant dataset.

Continuous airborne simulation driven by wall-clock time: racetrack cruise at
8,500 ft with a repeating test-point cycle (doublets, SHSS, bank sweep) so
every panel of the IADS workbook animates in LIVE mode. All data synthetic.

Usage: stream_live_flight.py [duration_minutes]  (default 45)
"""
import math
import random
import sys
import time
from datetime import datetime, timezone

from nominal.core import NominalClient

DATASET_RID = "ri.catalog.cerulean-staging.dataset.17813f61-cf19-4cb4-9a79-0e2cf36599a0"
HZ = 5.0
DUR_MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0

R = random.Random(7)
def n(s):  # gaussian noise
    return R.gauss(0, s)

# ---------------------------------------------------------------- test cycle
# (duration_s, label) — repeats forever
CYCLE = [
    (40, "CRUISE"),
    (15, "TP-11 Pitch Doublet"),
    (20, "CRUISE"),
    (15, "TP-12 Roll Doublet"),
    (20, "CRUISE"),
    (15, "TP-13 Rudder Doublet"),
    (20, "CRUISE"),
    (40, "TP-14 Steady Heading Sideslip"),
    (20, "CRUISE"),
    (90, "TP-15 Bank Sweep 30/45/60"),
    (45, "CRUISE"),
]
CYCLE_LEN = sum(d for d, _ in CYCLE)

def phase_at(t):
    """Return (label, time_into_phase) for cycle time t."""
    tc = t % CYCLE_LEN
    for d, label in CYCLE:
        if tc < d:
            return label, tc
        tc -= d
    return "CRUISE", 0.0

def doublet(tp, period, amp):
    """Symmetric doublet over [0, period], zero outside."""
    if tp < 0 or tp >= period:
        return 0.0
    return amp if tp < period / 2 else -amp

# ---------------------------------------------------------------- state
class Sim:
    def __init__(self):
        self.lat, self.lon = 35.02, -118.10   # test-area entry point
        self.hdg = 120.0
        self.fuel = 58.0
        self.tmps = {"e": 46.0, "al": 46.0, "ar": 46.0, "r": 46.0}

    def tick(self, t, dt):
        label, tp = phase_at(t)

        # -------- racetrack heading: 180-deg turn every 180 s over 30 s
        leg = (t % 360.0)
        turn = 0.0
        if 150.0 <= leg < 180.0:
            turn = 6.0     # deg/s right turn -> +180
        elif 330.0 <= leg < 360.0:
            turn = 6.0
        self.hdg = (self.hdg + turn * dt) % 360.0

        # -------- maneuver injections
        d_elev = d_ail = d_rud = 0.0
        beta_cmd = 0.0
        bank_extra = 0.0
        if label.startswith("TP-11"):
            d_elev = doublet(tp - 3, 8, 6.0)
        elif label.startswith("TP-12"):
            d_ail = doublet(tp - 3, 6, 9.0)
        elif label.startswith("TP-13"):
            d_rud = doublet(tp - 3, 10, 8.0)
        elif label.startswith("TP-14"):
            beta_cmd = 8.0 * math.sin(2 * math.pi * (tp / 40.0))
        elif label.startswith("TP-15"):
            bank_extra = 30.0 if tp < 30 else (45.0 if tp < 60 else 60.0)
            bank_extra *= math.sin(math.pi * min(tp % 30, 6) / 6) if (tp % 30) < 6 else 1.0

        # -------- flight state
        ias = 130.0 + 4 * math.sin(2 * math.pi * t / 97) + n(0.5)
        alt = 8500.0 + 40 * math.sin(2 * math.pi * t / 210) + n(3)
        vs = 40 * math.cos(2 * math.pi * t / 210) * (2 * math.pi / 210) * 60 + n(12)
        oat = 32.0 - 1.98 * (alt - 2790) / 1000 + n(0.1)
        tas = ias * (1 + 0.015 * (alt - 2790) / 1000)
        mach = tas / (661.5 * math.sqrt((oat + 273.15) / 288.15))
        sp = 14.696 * (1 - 6.8756e-6 * alt) ** 5.2559

        roll = (25.0 if turn else 0.0) + bank_extra + d_ail * 1.5 + n(0.4)
        pitch = 3.0 + d_elev * 0.7 + n(0.15)
        aoa = 2.0 + (130 - ias) * 0.09 + pitch * 0.15 + n(0.1)
        beta = beta_cmd + d_rud * 0.7 + n(0.2)
        p_r = d_ail * 2.0 + (0.5 if turn else 0) + n(0.5)
        q_r = d_elev * 0.8 + n(0.4)
        r_t = turn + d_rud * 0.9 + beta_cmd * 0.1 + n(0.3)
        nz = 1.0 / max(math.cos(math.radians(min(abs(roll), 60))), 0.5) + q_r * 0.02 + n(0.02)
        nx = n(0.01)
        ny = beta * 0.02 + n(0.008)

        elev = -pitch * 0.6 - 1.2 + d_elev + n(0.1)
        aill = roll * 0.25 + d_ail + n(0.1)
        ailr = -aill + n(0.08)
        rud = beta * 0.8 + d_rud + n(0.1)
        flap, trim = 0.0 + n(0.02), 1.1 + n(0.02)

        cur = {
            "e": min(0.8 + abs(d_elev) * 1.2 + abs(q_r) * 0.3, 12) + n(0.05),
            "al": min(0.8 + abs(d_ail) * 1.1 + abs(p_r) * 0.25, 12) + n(0.05),
            "ar": min(0.8 + abs(d_ail) * 1.1 + abs(p_r) * 0.25, 12) + n(0.05),
            "r": min(0.8 + abs(d_rud) * 1.2 + abs(beta_cmd) * 0.4, 12) + n(0.05),
        }
        for k in self.tmps:
            self.tmps[k] += (0.9 * cur[k] - (self.tmps[k] - oat) * 0.012) * dt
        thr = 75.0 + 3 * math.sin(2 * math.pi * t / 120) + n(0.3)
        rpm = 750 + thr * 24.5 + n(6)
        ff = 1.2 + thr * 0.165 + n(0.05)
        self.fuel = max(self.fuel - ff * dt / 3600.0, 0)
        egt = 620 + thr * 2.1 + n(1.5)
        cht = 95 + thr * 0.85 + n(0.4)
        oilt = 60 + thr * 0.35 + n(0.15)
        oilp = 28 + rpm * 0.011 + n(0.3)
        man_p = 10 + thr * 0.19 - (alt - 2790) * 2.2e-4

        tot_cur = sum(cur.values())
        busv = 27.8 - tot_cur * 0.01 + n(0.04)
        busa = 22 + tot_cur + n(0.3)
        batv = 25.1 + n(0.02)
        batt = 28 + busa * 0.08 + n(0.08)

        gs = max(tas + 8 * math.cos(math.radians(self.hdg - 250)), 0)
        d = gs * 0.514444 * dt
        self.lat += d * math.cos(math.radians(self.hdg)) / 111111.0
        self.lon += d * math.sin(math.radians(self.hdg)) / (111111.0 * math.cos(math.radians(self.lat)))
        # keep inside the test area box
        self.lat = min(max(self.lat, 34.55), 35.25)
        self.lon = min(max(self.lon, -118.45), -117.75)

        return {
            "flight.ias_kts": ias, "flight.tas_kts": tas, "flight.altitude_ft": alt,
            "flight.radalt_ft": alt - 2790, "flight.vspeed_fpm": vs, "flight.mach": mach,
            "attitude.roll_deg": roll, "attitude.pitch_deg": pitch, "attitude.heading_deg": self.hdg,
            "attitude.aoa_deg": aoa, "attitude.beta_deg": beta,
            "rates.p_dps": p_r, "rates.q_dps": q_r, "rates.r_dps": r_t,
            "accel.nx_g": nx, "accel.ny_g": ny, "accel.nz_g": nz,
            "controls.elevator_deg": elev, "controls.aileron_l_deg": aill,
            "controls.aileron_r_deg": ailr, "controls.rudder_deg": rud,
            "controls.flap_deg": flap, "controls.stab_trim_deg": trim,
            "actuators.elev_current_a": cur["e"], "actuators.ail_l_current_a": cur["al"],
            "actuators.ail_r_current_a": cur["ar"], "actuators.rud_current_a": cur["r"],
            "actuators.elev_temp_c": self.tmps["e"], "actuators.ail_l_temp_c": self.tmps["al"],
            "actuators.ail_r_temp_c": self.tmps["ar"], "actuators.rud_temp_c": self.tmps["r"],
            "engine.rpm": rpm, "engine.egt_c": egt, "engine.cht_c": cht,
            "engine.oil_press_psi": oilp, "engine.oil_temp_c": oilt,
            "engine.fuel_flow_gph": ff, "engine.fuel_qty_gal": self.fuel,
            "engine.throttle_pct": thr, "engine.manifold_press_inhg": man_p,
            "elec.bus_volts": busv, "elec.bus_amps": busa,
            "elec.batt_volts": batv, "elec.batt_temp_c": batt,
            "gps.latitude_deg": self.lat, "gps.longitude_deg": self.lon,
            "gps.ground_speed_kts": gs, "gps.track_deg": self.hdg,
            "gps.num_sats": 11 + (R.randint(-1, 1)),
            "env.oat_c": oat, "env.static_press_psi": sp,
            "test.test_active": 0.0 if phase_at(t)[0] == "CRUISE" else 1.0,
        }, label


def main():
    client = NominalClient.from_profile(profile="prod_demo_workspace")
    ds = client.get_dataset(DATASET_RID)
    sim = Sim()
    t0 = time.time()
    end = t0 + DUR_MIN * 60
    ticks = 0
    print(f"streaming to {DATASET_RID} at {HZ} Hz for {DUR_MIN:.0f} min", flush=True)
    with ds.get_write_stream(batch_size=1000, data_format="json") as ws:
        last = t0
        while time.time() < end:
            now = time.time()
            dt = max(now - last, 1e-3)
            last = now
            vals, label = sim.tick(now - t0, dt)
            ts = datetime.now(timezone.utc)
            for chan, val in vals.items():
                ws.enqueue(chan, ts, float(val))
            ws.enqueue("test.test_point", ts, label)
            ticks += 1
            if ticks % 150 == 0:
                print(f"  t+{now - t0:6.0f}s  {label:32} alt={vals['flight.altitude_ft']:.0f} "
                      f"ias={vals['flight.ias_kts']:.0f} roll={vals['attitude.roll_deg']:+.1f}", flush=True)
            time.sleep(max(0, (1.0 / HZ) - (time.time() - now)))
    print("stream closed", flush=True)


if __name__ == "__main__":
    main()
