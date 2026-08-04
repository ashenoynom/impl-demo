#!/usr/bin/env python3
"""Stand up the Ascent MC Build 47 demo in Nominal (Track A small campaign).

Per https://docs.nominal.io/core/documentation/platform/simulation/setup:
one dataset for the model, three tags on every point
(model_name / sim_number / run_number), one first-class run per sim run.

Idempotent: searches for the dataset and runs before creating, so reruns
don't duplicate. Targets the workspace configured on the nom profile.

Usage:
    python stand_up.py [--profile demo_space_prod] [--skip-upload]
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nominal.core import NominalClient
from nominal.core.event import EventType
from nominal.ts import Relative

HERE = Path(__file__).resolve().parent
DATA_CSV = HERE / "ascent_mc_build47.csv"
META_CSV = HERE / "ascent_mc_build47_run_metadata.csv"

PROFILE = "demo_space_prod"
DATASET_NAME = "LV-2 GNC simulation"
SIM_NUMBER = "Ascent MC Build 47"
RUN_LABEL = "LV-2"
NUM_RUNS = 10
EPOCH0 = datetime(1970, 1, 1, tzinfo=timezone.utc)
RUN_END_S = 580.0
EXPECTED_CHANNELS = 8  # 7 numeric + flight_phase

PROPERTY_KEYS = [
    "sim_number",
    "seed",
    "thrust_s1_factor",
    "thrust_s2_factor",
    "isp_factor",
    "prop_load_factor",
    "drag_factor",
    "wind_bias_mps",
]


def load_metadata() -> dict[str, dict[str, str]]:
    with META_CSV.open() as f:
        return {row["run_number"]: row for row in csv.DictReader(f)}


def get_or_create_dataset(client: NominalClient):
    existing = client.search_datasets(exact_match=DATASET_NAME)
    for ds in existing:
        if ds.name == DATASET_NAME:
            print(f"Found existing dataset: {ds.name} ({ds.rid})")
            return ds, False
    ds = client.create_dataset(
        name=DATASET_NAME,
        description=(
            "Two-stage LOX/RP-1 launch vehicle ascent simulation. "
            "Monte Carlo output tagged by model_name / sim_number / run_number."
        ),
        labels=[RUN_LABEL],
        properties={"model_name": DATASET_NAME},
    )
    print(f"Created dataset: {ds.name} ({ds.rid})")
    return ds, True


def upload_csv(dataset) -> None:
    print(f"Uploading {DATA_CSV.name} (relative-seconds timestamps, 3 tag columns)...")
    dataset_file = dataset.add_tabular_data(
        DATA_CSV,
        timestamp_column="time_s",
        timestamp_type=Relative("seconds", start=EPOCH0),
        tag_columns={
            "model_name": "model_name",
            "sim_number": "sim_number",
            "run_number": "run_number",
        },
    )
    print("Waiting for ingestion to complete...")
    dataset_file.poll_until_ingestion_completed()
    dataset.refresh()
    channels = list(dataset.get_channels())
    names = sorted(c.name for c in channels)
    print(f"Ingestion complete. {len(channels)} channels: {names}")
    if len(channels) != EXPECTED_CHANNELS:
        print(
            f"WARNING: expected {EXPECTED_CHANNELS} channels "
            f"(7 numeric + flight_phase), got {len(channels)}"
        )


def get_or_create_runs(client: NominalClient, dataset, metadata) -> list:
    runs = []
    for n in range(1, NUM_RUNS + 1):
        title = f"{SIM_NUMBER}: Run {n}"
        found = client.search_runs(exact_match=title)
        run = next((r for r in found if r.name == title), None)
        if run is not None:
            print(f"Run exists, skipping create: {title} ({run.rid})")
        else:
            meta = metadata[str(n)]
            props = {k: str(meta[k]) for k in PROPERTY_KEYS if k in meta}
            run = client.create_run(
                name=title,
                start=EPOCH0,
                end=EPOCH0 + timedelta(seconds=RUN_END_S),
                description=(
                    f"{SIM_NUMBER} dispersion {n} of {NUM_RUNS}"
                    + (" (nominal case)" if n == 1 else "")
                ),
                labels=[RUN_LABEL],
                properties=props,
            )
            print(f"Created run: {title} ({run.rid})")

        # Attach the tag-filtered data scope (idempotent-ish: skip if present)
        try:
            existing_scopes = {rn for rn, _ in run.list_datasets()}
        except Exception:
            existing_scopes = set()
        if "default" in existing_scopes:
            print(f"  data scope 'default' already attached")
        else:
            try:
                run.add_dataset(
                    "default",
                    dataset,
                    series_tags={"sim_number": SIM_NUMBER, "run_number": str(n)},
                )
                print(f"  attached data scope 'default' with tag filter run_number={n}")
            except Exception as e:
                print(
                    f"  WARNING: could not attach tag-filtered data scope via SDK "
                    f"({e}); set it manually in the app for {title}"
                )
        runs.append(run)
    return runs


def create_events(runs, metadata) -> None:
    for n, run in enumerate(runs, start=1):
        meta = metadata[str(n)]
        t_meco = float(meta["t_meco_s"])
        t_seco = float(meta["t_seco_s"])
        t_deploy = float(meta["t_deploy_s"])
        timeline = [
            ("MECO", t_meco, EventType.INFO),
            ("Stage separation", t_meco + 3.0, EventType.INFO),
            ("Stage 2 ignition", t_meco + 6.0, EventType.INFO),
            ("SECO", t_seco, EventType.INFO),
            ("Payload deploy", t_deploy, EventType.SUCCESS),
        ]
        try:
            existing = {e.name for e in run.search_events()}
        except Exception:
            existing = set()
        for name, t_s, etype in timeline:
            if name in existing:
                continue
            try:
                run.create_event(
                    name,
                    etype,
                    EPOCH0 + timedelta(seconds=t_s),
                    labels=[RUN_LABEL],
                    properties={"run_number": str(n)},
                )
            except Exception as e:
                print(f"  events API failed on run {n} ({name}): {e} — continuing")
                break
        print(f"Events ensured for run {n} (MECO {t_meco}s, SECO {t_seco}s, deploy {t_deploy}s)")


def verify(client: NominalClient, dataset, runs) -> None:
    found = client.search_runs(name_substring=SIM_NUMBER)
    build_runs = [r for r in found if r.name.startswith(f"{SIM_NUMBER}: Run ")]
    print(f"\nVerification: {len(build_runs)} runs found for '{SIM_NUMBER}' (expected {NUM_RUNS})")

    print("\n=== URLs ===")
    print(f"Dataset: {dataset.nominal_url}")
    for run in runs:
        print(f"{run.name}: {run.nominal_url}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Skip the CSV upload (dataset already ingested)",
    )
    args = parser.parse_args()

    client = NominalClient.from_profile(args.profile)
    user = client.get_user()
    print(f"Authenticated as: {user.display_name} ({user.email})")
    workspace_rid = client._clients.resolve_default_workspace_rid()
    for ws in client.list_workspaces():
        if ws.rid == workspace_rid:
            print(f"Target workspace: {ws.name} ({ws.rid})")
            break
    else:
        print(f"Target workspace rid (not listed?): {workspace_rid}")

    metadata = load_metadata()
    dataset, created = get_or_create_dataset(client)
    if args.skip_upload:
        print("Skipping upload (--skip-upload)")
    elif not created and any(True for _ in dataset.get_channels()):
        print("Dataset already has channels; skipping upload (pass no flag to force is not supported — delete the file in-app to re-ingest)")
    else:
        upload_csv(dataset)

    runs = get_or_create_runs(client, dataset, metadata)
    create_events(runs, metadata)
    verify(client, dataset, runs)


if __name__ == "__main__":
    main()
