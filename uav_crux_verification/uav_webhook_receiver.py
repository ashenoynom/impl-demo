#!/usr/bin/env python3
"""Verification-uplink webhook receiver.

Nominal fires a POST here when a procedure's "Transmit scenario command"
step completes (send_notification → the "verification-uplink" simple-webhook
integration). The notification message carries a routing token —

    requirement=<EXT>;tc=<EXT>;window=<seconds>

— which this receiver extracts from anywhere in the payload (shape-agnostic:
it scans every string in the JSON, and the raw body as fallback), then queues
the scenario on the shared command file. The streamer plays it and acks; the
orchestrator consumes the ack.

Usage:
    python3 -u uav_webhook_receiver.py [--port 8766]

    # after starting a tunnel (cloudflared tunnel --url http://localhost:8766):
    python3 uav_webhook_receiver.py --public-url https://xxxx.trycloudflare.com
    # (repoints the integration and exits; run the server separately)
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from command_file import locked_update
from staging_env import PROFILE

TOKEN_RE = re.compile(r"requirement=([A-Z0-9\-]+);tc=([A-Z0-9\-]+);window=(\d+)")


def find_token(payload: object, raw: str) -> tuple[str, str, float] | None:
    strings: list[str] = [raw]

    def walk(node: object) -> None:
        if isinstance(node, str):
            strings.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(payload)
    for s in strings:
        m = TOKEN_RE.search(s)
        if m:
            return m.group(1), m.group(2), float(m.group(3))
    return None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode(errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}

        ts = datetime.now().strftime("%H:%M:%S")
        token = find_token(payload, raw)
        if token is None:
            print(f"[{ts}] POST with no routing token — 200 anyway. Body: {raw[:300]}")
        else:
            requirement, tc, window = token
            sid = str(uuid.uuid4())

            def queue(state: dict) -> None:
                state["scenarios"][sid] = {
                    "id": sid,
                    "requirement_ext": requirement,
                    "test_case_id": tc,
                    "window_s": window,
                    "queued_at": datetime.now().isoformat(),
                }

            locked_update(queue)
            print(f"[{ts}] ⚡ scenario queued: {requirement}/{tc} ({window:.0f}s) [{sid[:8]}]")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args):  # quiet default access log
        pass


def repoint_integration(public_url: str) -> None:
    from nominal.core import NominalClient
    from nominal.core._utils.networking import create_conjure_client_factory
    from nominal_api.scout_integrations_api import (
        IntegrationsService,
        UpdateIntegrationDetailsRequest,
        UpdateSimpleWebhookDetails,
    )
    import json as _json
    import pathlib

    rids = _json.loads((pathlib.Path(__file__).parent / "uav_rids.json").read_text())
    client = NominalClient.from_profile(PROFILE)
    c = client._clients
    svc = create_conjure_client_factory(
        user_agent=c._user_agent,
        service_config=c._service_config,
        header_provider=c.header_provider,
    )(IntegrationsService)
    svc.update_integration_details(
        c.auth_header,
        rids["uplink_integration_rid"],
        UpdateIntegrationDetailsRequest(
            update_integration_details=_build_update(public_url)
        ),
    )
    print(f"✅ verification-uplink integration → {public_url}")


def _build_update(public_url: str):
    from nominal_api.scout_integrations_api import (
        UpdateIntegrationDetails,
        UpdateSimpleWebhookDetails,
    )

    return UpdateIntegrationDetails(
        simple_webhook=UpdateSimpleWebhookDetails(webhook=public_url)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--public-url", help="repoint the integration and exit")
    args = parser.parse_args()

    if args.public_url:
        repoint_integration(args.public_url.rstrip("/"))
        return

    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"verification-uplink receiver listening on :{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
