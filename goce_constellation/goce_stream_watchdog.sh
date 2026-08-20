#!/bin/bash
# Watchdog for the GOCE telemetry streamers.
#
# The nominal write stream can silently wedge after ~2-3 h (0% CPU, no
# errors, points just stop landing). This loop checks how old the newest
# GOCE-7 point is and restarts both streamers when it goes stale.
#
# Usage:  ./goce_stream_watchdog.sh [check_interval_s] [stale_threshold_s]
# Run it in its own terminal next to the streamers (or nohup it).

cd "$(dirname "$0")"
INTERVAL="${1:-90}"
STALE_S="${2:-240}"
LOG_DIR="${TMPDIR:-/tmp}"

age_check() {
  python3 - <<'EOF' 2>/dev/null
from nominal.core import NominalClient
from nominal.thirdparty.pandas import channel_to_series
from datetime import datetime, timedelta, timezone
try:
    c = NominalClient.from_profile('space_demo_prod')
    ds = c.get_dataset("ri.catalog.cerulean-staging.dataset.7fc2eee9-0908-4923-a233-3786736f3f81")
    ch = next(x for x in ds.search_channels(exact_match="eps.bus.current_a")
              if x.name == "eps.bus.current_a")
    end = datetime.now(timezone.utc)
    s = channel_to_series(ch, start=end - timedelta(minutes=30), end=end,
                          tags={"satellite": "GOCE-7"})
    if len(s) == 0:
        print(99999)
    else:
        print(int((end - s.index.max().to_pydatetime()).total_seconds()))
except Exception:
    print(-1)  # API hiccup — do not restart on a failed check
EOF
}

echo "[watchdog] up — checking every ${INTERVAL}s, restart when newest point > ${STALE_S}s old"
while true; do
  AGE=$(age_check)
  TS=$(date "+%H:%M:%S")
  if [ "$AGE" = "-1" ] || [ -z "$AGE" ]; then
    echo "[$TS] check failed (API hiccup) — skipping"
  elif [ "$AGE" -gt "$STALE_S" ]; then
    echo "[$TS] STALE (${AGE}s) — restarting streamers"
    pkill -f goce_csv_streamer.py
    pkill -f goce_log_streamer.py
    sleep 3
    nohup python3 -u goce_csv_streamer.py --profile goce_streamer --num-satellites 25 \
        >> "$LOG_DIR/goce_csv_streamer_watchdog.log" 2>&1 &
    nohup python3 -u goce_log_streamer.py --profile goce_streamer --num-satellites 25 \
        >> "$LOG_DIR/goce_log_streamer_watchdog.log" 2>&1 &
    echo "[$TS] relaunched (csv pid $!, logs in $LOG_DIR); allowing 5 min to reload"
    sleep 300
  else
    echo "[$TS] ok (newest ${AGE}s old)"
  fi
  sleep "$INTERVAL"
done
