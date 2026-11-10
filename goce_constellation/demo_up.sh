#!/bin/bash
# Stand up the full GOCE demo stack (idempotent — kills any old instances).
# Processes are nohup'd so they survive terminal/session teardown.
#
#   ./demo_up.sh          # start everything, reset fault to nominal
#   ./demo_up.sh status   # show process + fault + tunnel state
#
# Logs land in ./logs/.

cd "$(dirname "$0")" || exit 1
mkdir -p logs

if [ "$1" = "status" ]; then
  echo "--- processes ---"
  pgrep -fl "goce_csv_streamer|goce_log_streamer|goce_webhook_receiver|goce_command_bridge|cloudflared tunnel"
  echo "--- fault ---"
  python3 goce_fault_injector.py status | head -8
  echo "--- tunnel ---"
  grep -o 'https://[a-z-]*\.trycloudflare\.com' logs/tunnel.log | head -1
  exit 0
fi

echo "Stopping any old instances..."
pkill -f "goce_csv_streamer|goce_log_streamer|goce_webhook_receiver|goce_command_bridge" 2>/dev/null
pkill -f "cloudflared tunnel --url http://localhost:8765" 2>/dev/null
sleep 2

echo "Resetting fault state to nominal..."
python3 goce_fault_injector.py reset

echo "Starting streamers, receiver, tunnel, bridge (nohup -> logs/)..."
nohup python3 -u goce_csv_streamer.py --profile goce_streamer --num-satellites 25 > logs/csv_streamer.log 2>&1 &
nohup python3 -u goce_log_streamer.py --profile goce_streamer --num-satellites 25 > logs/log_streamer.log 2>&1 &
nohup python3 -u goce_webhook_receiver.py --profile space_demo_prod > logs/receiver.log 2>&1 &
# --protocol http2: QUIC (the default) is blocked on some networks
nohup cloudflared tunnel --url http://localhost:8765 --protocol http2 > logs/tunnel.log 2>&1 &
nohup python3 -u goce_command_bridge.py --profile space_demo_prod > logs/bridge.log 2>&1 &
disown -a 2>/dev/null

echo "Waiting for tunnel URL..."
TUNNEL=""
for i in $(seq 1 30); do
  TUNNEL=$(grep -o 'https://[a-z-]*\.trycloudflare\.com' logs/tunnel.log 2>/dev/null | head -1)
  [ -n "$TUNNEL" ] && break
  sleep 2
done
if [ -z "$TUNNEL" ]; then
  echo "WARN: no tunnel URL after 60 s — check logs/tunnel.log; integration NOT repointed"
else
  echo "Tunnel: $TUNNEL — repointing 'procedures' integration..."
  python3 -c "
from nominal.core import NominalClient
from goce_webhook_receiver import update_integration_url
update_integration_url(NominalClient.from_profile('space_demo_prod'), '$TUNNEL')
"
  sleep 2
  echo "Webhook smoke test:"
  curl -s -m 15 -X POST "$TUNNEL" -d '{"smoke":"demo_up"}' | head -c 120; echo
fi

echo ""
echo "Stack is up. CSV streamer needs ~2 min to load before data flows."
echo "Arm the fault with:  python3 goce_fault_injector.py arm --event"
