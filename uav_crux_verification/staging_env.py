"""Shared constants for the RTX/UAV automated requirements-verification demo.

Everything targets gov STAGING. The Nova key-value routes (Crux Lite's
document store) are served on the APP host, not the API host — the API host
answers a bare nginx 404 for them.
"""

from __future__ import annotations

PROFILE = "anish_staging_default"

API_BASE = "https://api-staging.gov.nominal.io/api"
APP_ORIGIN = "https://app-staging.gov.nominal.io"
WORKSPACE_RID = "ri.security.gov-staging.workspace.7d802d4e-7f1c-45b9-ba05-f7f6323504d6"
WORKSPACE_URL = f"{APP_ORIGIN}/w/{WORKSPACE_RID}"

# Crux Lite (Nova app) on gov staging; its ProjectDoc lives in the per-app KV
# store under project id "default" (the app hardcodes it in index.tsx).
CRUX_APP_RID = "ri.nova.gov-staging.app.67127f04-26d0-4edf-9fbe-faee5c3a2a00"
CRUX_PROJECT_ID = "default"

# How Crux Lite maps Core runs into the project (from ProjectSettings):
# runs are in scope when property crux_project == "UAV", and a run binds to a
# test case through the run property named by testCaseKeyProperty.
CRUX_PROJECT_PROPERTY = "crux_project"
CRUX_PROJECT_VALUE = "UAV"
TEST_CASE_KEY_PROPERTY = "test_case_id"

# Attribution stamped on rows this tooling writes into the Crux doc.
ACTOR_ID = "system:verification-orchestrator"
ACTOR_NAME = "Verification orchestrator"


def token() -> str:
    """API token for the staging profile, read from the nominal config."""
    import pathlib

    import yaml

    cfg = yaml.safe_load((pathlib.Path.home() / ".config/nominal/config.yml").read_text())
    return cfg["profiles"][PROFILE]["token"]
