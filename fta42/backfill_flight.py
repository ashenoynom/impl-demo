#!/usr/bin/env python3
"""Backfill the live FTA-42 simulation into the past so the stream reads
as picking up mid-flight. Reuses the exact Sim from stream_live_flight so
statistics match; duration is a whole number of racetrack cycles so the
end position splices onto the live stream's starting point."""
import csv
from datetime import datetime, timezone

from stream_live_flight import Sim, phase_at

SPLICE_END = 1784828138.0        # 2 s before first live point
CYCLES = 18                       # 18 x 360 s racetrack legs = 6480 s
DUR = CYCLES * 360.0
HZ = 5.0
START = SPLICE_END - DUR

sim = Sim()
dt = 1.0 / HZ
rows = []
t = 0.0
while t < DUR:
    vals, label = sim.tick(t, dt)
    ts = datetime.fromtimestamp(START + t, tz=timezone.utc)
    row = {"timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
           "test.test_point": label}
    row.update({k: round(v, 4) for k, v in vals.items()})
    rows.append(row)
    t += dt

cols = ["timestamp"] + [c for c in rows[0] if c != "timestamp"]
out = __file__.rsplit("/", 1)[0] + "/fta42_backfill.csv"
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
print(f"wrote {out}: {len(rows)} rows, "
      f"{rows[0]['timestamp']} -> {rows[-1]['timestamp']}")
print("end lat/lon:", rows[-1]["gps.latitude_deg"], rows[-1]["gps.longitude_deg"])
