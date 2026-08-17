#!/usr/bin/env python3
"""GOCE ground-segment webhook receiver — HTR2_PWR_CYCLE command handler.

Nominal fires a POST to this server when the procedure operator completes
the "Transmit HTR2_PWR_CYCLE command" step (via its "Send notification"
completion action). The receiver:

  1. Writes command_state.json → "recovering"  (streamers pick it up ~2 s)
  2. Creates a CMD-accepted event on the GOCE-7 asset timeline
  3. Returns HTTP 200 so Nominal marks the notification delivered

Optionally updates the "procedures" webhook integration in Nominal to
point at the public URL (pass --public-url after running ngrok).

Usage:
    # Terminal 4 — run before (or instead of) goce_command_bridge.py transmit
    python3 goce_webhook_receiver.py [--profile space_demo_prod] [--port 8765]

    # One-time setup: expose publicly + update Nominal integration URL
    ngrok http 8765
    python3 goce_webhook_receiver.py --public-url https://xxxx.ngrok.io [--profile ...]

    # The command bridge still handles close-out; run it separately:
    python3 goce_command_bridge.py --profile space_demo_prod
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from nominal.core import NominalClient
from nominal.core.event import EventType

from goce_limits import (
    COMMAND_NAME,
    FAULT_SATELLITE,
    read_command_state,
    write_command_state,
)

WEBHOOK_INTEGRATION_RID = (
    "ri.scout.cerulean-staging.integration.d142937d-63de-4998-b1fa-f8744a3528fd"
)
INTEGRATION_API_PATH = "/api/scout/v2/integrations"


def update_integration_url(client: NominalClient, public_url: str) -> None:
    """Point the 'procedures' webhook integration at this server.

    Conjure: PUT /scout/v2/integrations/{integrationRid}/details with an
    UpdateIntegrationDetailsRequest whose union member is simpleWebhook
    (UpdateSimpleWebhookDetails.webhook = the URL)."""
    import requests

    token = client._clients.auth_header
    resp = requests.put(
        "https://api.gov.nominal.io/api/scout/v2/integrations/"
        f"{WEBHOOK_INTEGRATION_RID}/details",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={
            "updateIntegrationDetails": {
                "type": "simpleWebhook",
                "simpleWebhook": {"webhook": public_url},
            }
        },
    )
    if resp.status_code == 200:
        print(f"✅ 'procedures' integration URL updated → {public_url}")
    else:
        print(
            f"⚠️  Auto-update failed (HTTP {resp.status_code}: {resp.text[:200]}). "
            f"Update manually: Workspace → Integrations → 'procedures' → URL = {public_url}"
        )


class CommandWebhookHandler(BaseHTTPRequestHandler):
    # Set by main() before the server starts
    client: NominalClient = None
    asset = None

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}

        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n{'='*60}")
        print(f"[{ts}] ⚡ WEBHOOK RECEIVED — CMD {COMMAND_NAME}")
        if payload:
            preview = json.dumps(payload, indent=2)
            print(preview[:600] + ("..." if len(preview) > 600 else ""))

        # --- heal the fault ---
        healed = False
        state = read_command_state()
        if state["state"] not in ("armed", "active"):
            print(
                f"[{ts}] No active fault (state: {state['state']}) — "
                "healing skipped; returning 200"
            )
        else:
            write_command_state(
                "recovering",
                t_armed=state.get("t_armed"),
                t_recovery=time.time(),
                source="webhook_receiver",
            )
            healed = True
            print(f"[{ts}] command_state.json → recovering  (streamers will heal in ~2 s)")

        # --- ACK event on GOCE-7 timeline (only when a command actually landed) ---
        if healed and self.asset is not None:
            try:
                event = self.asset.create_event(
                    name=f"CMD {COMMAND_NAME} accepted by {FAULT_SATELLITE}",
                    type=EventType.SUCCESS,
                    start=datetime.now(timezone.utc),
                    description=(
                        "Spacecraft ACK: HTR-2 heater controller power-cycled via webhook. "
                        f"Bus current recovering — expected tau ~45 s."
                    ),
                    labels=["GOCE", "command", "HTR-2", "ack"],
                    properties={"command": COMMAND_NAME, "source": "webhook"},
                )
                print(f"[{ts}] ACK event → {event.rid}")
            except Exception as exc:
                print(f"[{ts}] ACK event failed: {exc}")

        print(f"{'='*60}\n")

        # Return 200 so Nominal marks the notification delivered
        response = json.dumps(
            {"status": "ok", "command": COMMAND_NAME, "state": "recovering"}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, fmt, *args):  # suppress default access log
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="space_demo_prod")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--public-url",
        metavar="URL",
        help="ngrok / public URL of this server — also updates the Nominal integration",
    )
    args = parser.parse_args()

    client = NominalClient.from_profile(args.profile)
    print(f"Authenticated as: {client.get_user().email}")

    asset = next(
        (a for a in client.search_assets(
            search_text=FAULT_SATELLITE,
            properties={"asset_id": FAULT_SATELLITE},
        ) if a.name == FAULT_SATELLITE),
        None,
    )
    if asset:
        print(f"Asset loaded: {asset.name} ({asset.rid})")
    else:
        print(f"⚠️  Asset {FAULT_SATELLITE!r} not found — ACK events will be skipped")

    if args.public_url:
        update_integration_url(client, args.public_url)

    CommandWebhookHandler.client = client
    CommandWebhookHandler.asset = asset

    server = HTTPServer(("", args.port), CommandWebhookHandler)
    print(f"\nWebhook receiver listening on :{args.port}")
    print(f"  Expose:  ngrok http {args.port}")
    print(f"  Then:    python3 goce_webhook_receiver.py --public-url <ngrok-url>")
    print(f"  Bridge:  python3 goce_command_bridge.py  (close-out only)\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nReceiver stopped.")


if __name__ == "__main__":
    main()
