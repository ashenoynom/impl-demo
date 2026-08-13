#!/usr/bin/env python3
"""Create the GOCE-7 ground-test dataset + comparison runs in Nominal.

Subcommands:
    ground      Upload data/goce7_eps_tvac_ground_test.csv as its own
                dataset and create the "TVAC HTR-2 anomaly replication"
                run on asset GOCE-7 (ref_name "data").
    flight-run  Create the flight anomaly run on asset GOCE-7 over a
                live window of the streaming dataset (default: the last
                45 minutes), ref_name "data", series tag satellite=GOCE-7.

Both runs carry ref_name "data", so the bus-health checklist (which
locates channels via data_source_ref="data") executes against either,
and the run-comparison workbook resolves the same hierarchical channel
names on both sides.

Usage:
    python goce_ground_setup.py ground [--profile space_demo_prod]
    python goce_ground_setup.py flight-run [--minutes 45] [--name "..."]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from nominal.core import NominalClient

GROUND_CSV = Path(__file__).resolve().parent / "data" / "goce7_eps_tvac_ground_test.csv"
GROUND_DATASET_NAME = "GOCE-7 EPS TVAC ground test (2026-03)"
TVAC_ASSET_NAME = "GOCE-7 FM — TVAC campaign"
GROUND_RUN_NAME = "GOCE-7 | TVAC HTR-2 anomaly replication (2026-03-14)"
FLIGHT_RUN_NAME_DEFAULT = "GOCE-7 | Flight EPS anomaly investigation"
# GOCE_Fleet_Streaming (hierarchical-only namespace, 2026-08-12)
STREAMING_DATASET_RID = "ri.catalog.cerulean-staging.dataset.7fc2eee9-0908-4923-a233-3786736f3f81"
ASSET_NAME = "GOCE-7"
DATA_REF_NAME = "data"


def get_asset(client: NominalClient):
    assets = client.search_assets(search_text=ASSET_NAME, properties={"asset_id": ASSET_NAME})
    asset = next((a for a in assets if a.name == ASSET_NAME), None)
    if asset is None:
        raise SystemExit(f"Asset {ASSET_NAME} not found — start the streamer first")
    return asset


def find_run_by_name(client: NominalClient, name: str):
    for run in client.search_runs(name_substring=name):
        if run.name == name:
            return run
    return None


def cmd_ground(client: NominalClient) -> None:
    if not GROUND_CSV.exists():
        raise SystemExit(f"{GROUND_CSV} missing — run make_ground_test_csv.py first")

    df = pd.read_csv(GROUND_CSV, usecols=["timestamp"])
    start = datetime.fromisoformat(df["timestamp"].iloc[0])
    end = datetime.fromisoformat(df["timestamp"].iloc[-1])

    existing = [d for d in client.search_datasets(search_text=GROUND_DATASET_NAME)
                if d.name == GROUND_DATASET_NAME]
    if existing:
        dataset = existing[0]
        print(f"Dataset exists: {dataset.name} ({dataset.rid}) — skipping upload")
    else:
        dataset = client.create_dataset(
            name=GROUND_DATASET_NAME,
            description=(
                "FM EPS thermal-vacuum bench data, 2026-03-14 hot plateau: "
                "HTR-2 heater controller latch-up replication and HTR2_PWR_CYCLE "
                "recovery. 1 Hz bench instrumentation, flight channel namespace."
            ),
            labels=["GOCE", "ground-test", "TVAC"],
            properties={"asset_id": ASSET_NAME, "campaign": "FM-TVAC-2026-03"},
            prefix_tree_delimiter=".",
        )
        print(f"Created dataset: {dataset.name} ({dataset.rid})")
        file = dataset.add_tabular_data(
            GROUND_CSV, timestamp_column="timestamp", timestamp_type="iso_8601"
        )
        print(f"Uploaded {GROUND_CSV.name} (file: {file.id if hasattr(file, 'id') else file})")
    print(f"Dataset URL: {dataset.nominal_url}")

    # IMPORTANT: run-level data source edits propagate to the attached
    # asset's scopes (bidirectionally) — attaching the ground run to the
    # flight GOCE-7 asset and rebinding "data" would clobber the live
    # streaming scope for every workbook. The bench run therefore lives
    # on its own campaign asset whose "data" scope IS the bench dataset.
    tvac = next(
        (a for a in client.search_assets(search_text=TVAC_ASSET_NAME) if a.name == TVAC_ASSET_NAME),
        None,
    )
    if tvac is None:
        tvac = client.create_asset(
            name=TVAC_ASSET_NAME,
            description=(
                "Bench/EGSE context for the GOCE-7 flight model during the "
                "2026-03 thermal-vacuum campaign. Data scope 'data' carries "
                "the TVAC bench instrumentation (flight channel namespace)."
            ),
            properties={"asset_id": "GOCE-7-TVAC", "campaign": "FM-TVAC-2026-03"},
            labels=["GOCE", "ground-test"],
        )
        tvac.add_dataset(data_scope_name=DATA_REF_NAME, dataset=dataset)
        print(f"Created TVAC campaign asset: {tvac.rid}")

    run = find_run_by_name(client, GROUND_RUN_NAME)
    if run is None:
        run = client.create_run(
            name=GROUND_RUN_NAME,
            start=start,
            end=end,
            description=(
                "TVAC hot-plateau replication of the HTR-2 heater controller "
                "latch-up: duty pins at 100%, bus current +1.0 A, bus voltage "
                "-0.25 V, bus temp +2.8 C. HTR2_PWR_CYCLE command at T+120 min "
                "breaks the latch; bus recovers with tau ~8 min. Reference "
                "signature for flight RCA."
            ),
            labels=["GOCE", "ground-test", "TVAC", "HTR-2"],
            properties={"asset_id": ASSET_NAME, "campaign": "FM-TVAC-2026-03",
                        "anomaly": "htr2_runaway"},
            assets=[tvac],
        )
        # The run inherits the TVAC asset's data scope (bench dataset on
        # ref "data") — exactly right; add only if inheritance missed.
        refs = {ref for ref, _ in run.list_datasets()}
        if DATA_REF_NAME not in refs:
            run.add_dataset(DATA_REF_NAME, dataset)
        print(f"Created run: {run.name} ({run.rid})")
    else:
        print(f"Run exists: {run.name} ({run.rid})")
    print(f"Run URL: {run.nominal_url}")


def cmd_flight_run(client: NominalClient, minutes: float, name: str) -> None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    asset = get_asset(client)

    run = find_run_by_name(client, name)
    if run is None:
        run = client.create_run(
            name=name,
            start=start,
            end=end,
            description=(
                "Flight anomaly window for the GOCE-7 EPS overcurrent / bus "
                "voltage sag alert: HTR-2 heater duty latched at 100%. Compare "
                f"against '{GROUND_RUN_NAME}' — identical signature, known "
                "corrective action HTR2_PWR_CYCLE."
            ),
            labels=["GOCE", "flight", "anomaly", "HTR-2"],
            properties={"asset_id": ASSET_NAME, "anomaly": "htr2_runaway"},
            assets=[asset],
        )
        # The run inherits the asset's "data" scope (streaming dataset
        # filtered to satellite=GOCE-7) — exactly what we want. Only add
        # explicitly if inheritance didn't happen.
        refs = {ref for ref, _ in run.list_datasets()}
        if DATA_REF_NAME not in refs:
            run.add_dataset(
                DATA_REF_NAME,
                STREAMING_DATASET_RID,
                series_tags={"satellite": ASSET_NAME},
            )
        print(f"Created run: {run.name} ({run.rid})")
    else:
        # Refresh the window in place (run rid is pinned by the
        # comparison workbook, so never recreate — just re-bound it).
        run = run.update(start=start, end=end)
        print(f"Run exists: {run.name} ({run.rid}) — window refreshed to last {minutes:.0f} min")
    print(f"Run URL: {run.nominal_url}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ground", "flight-run"])
    parser.add_argument("--profile", default="space_demo_prod")
    parser.add_argument("--minutes", type=float, default=45.0,
                        help="flight-run: window length ending now")
    parser.add_argument("--name", default=FLIGHT_RUN_NAME_DEFAULT,
                        help="flight-run: run name")
    args = parser.parse_args()

    client = NominalClient.from_profile(args.profile)
    print(f"Authenticated as: {client.get_user().email}")
    if args.command == "ground":
        cmd_ground(client)
    else:
        cmd_flight_run(client, args.minutes, args.name)


if __name__ == "__main__":
    main()
