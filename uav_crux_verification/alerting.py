"""Campaign notifications: Slack via a Nominal integration, with fallbacks.

Resolution order for the Slack integration rid:
1. "slack_integration_rid" in uav_rids.json (set it once the demo channel's
   integration exists);
2. auto-discovery: the newest slackWebhookIntegration whose channel name
   contains SLACK_CHANNEL_HINT;
3. none found → alerts print to stdout only (still loud, never fatal).

Every alert also lands as an event on the UAV-1 asset timeline, so the
notification trail is part of the demo data itself.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

from nominal.core import NominalClient
from nominal.core.event import EventType

RIDS_PATH = pathlib.Path(__file__).parent / "uav_rids.json"
SLACK_CHANNEL_HINT = "verification"  # matches e.g. #demo-uav-verification


class Alerter:
    def __init__(self, client: NominalClient):
        self.client = client
        self.rids = json.loads(RIDS_PATH.read_text())
        self._svc = None
        self._slack_rid = self.rids.get("slack_integration_rid") or self._discover()

    def _service(self):
        if self._svc is None:
            from nominal.core._utils.networking import create_conjure_client_factory
            from nominal_api.scout_integrations_api import IntegrationsService

            c = self.client._clients
            self._svc = create_conjure_client_factory(
                user_agent=c._user_agent,
                service_config=c._service_config,
                header_provider=c.header_provider,
            )(IntegrationsService)
        return self._svc

    def _discover(self) -> str | None:
        try:
            integrations = self._service().list_integrations(self.client._clients.auth_header)
        except Exception:
            return None
        candidates = []
        for integration in integrations:
            details = integration.integration_details
            slack = getattr(details, "slack_webhook_integration", None)
            if slack is None or integration.is_archived:
                continue
            if SLACK_CHANNEL_HINT in (slack.channel or "").lower():
                candidates.append(integration)
        if not candidates:
            return None
        rid = sorted(candidates, key=lambda i: i.created_at)[-1].rid
        print(f"[alerting] discovered Slack integration: {rid}")
        return rid

    def send(self, title: str, message: str, *, kind: str = "INFO") -> None:
        stamp = datetime.now(timezone.utc)
        print(f"\n{'🟢' if kind == 'PASS' else '🔴' if kind == 'FAIL' else 'ℹ️'} ALERT [{kind}] {title}\n{message}\n")
        if self._slack_rid:
            try:
                from nominal_api.scout_checks_api import Priority  # noqa: F401 (unused, priority optional)
                from nominal_api.scout_integrations_api import SendMessageRequest

                self._service().send_message(
                    self.client._clients.auth_header,
                    SendMessageRequest(
                        integration_rid=self._slack_rid,
                        title=title,
                        message=message,
                        tags=["verification-campaign", kind.lower()],
                    ),
                )
            except Exception as exc:  # alerting must never kill the campaign
                print(f"[alerting] Slack send failed: {exc}")
        try:
            asset = self.client.get_asset(self.rids["asset_rid"])
            asset.create_event(
                name=title,
                type=EventType.SUCCESS if kind == "PASS" else EventType.ERROR if kind == "FAIL" else EventType.INFO,
                start=stamp,
                duration=timedelta(seconds=1),
                description=message[:1000],
                labels=["verification", "alert", kind.lower()],
            )
        except Exception as exc:
            print(f"[alerting] timeline event failed: {exc}")
