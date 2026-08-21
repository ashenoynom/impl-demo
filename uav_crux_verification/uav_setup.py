#!/usr/bin/env python3
"""One-time setup: UAV-1 asset + streaming dataset on gov staging.

Creates (idempotently, by name search):
- dataset "UAV_Verification_Streaming" (hierarchical channel tree, '.'),
- asset "UAV-1" with data scope ref "data" → that dataset.

The scope ref name "data" is load-bearing: the published checklists resolve
their channels through ChannelLocator(data_source_ref="data"), and campaign
runs inherit the scope from the asset at create_run(assets=[UAV-1]).

Writes uav_rids.json next to this file for the other scripts.
"""

from __future__ import annotations

import json
import pathlib

from nominal.core import NominalClient

from staging_env import PROFILE, WORKSPACE_URL

DATASET_NAME = "UAV_Verification_Streaming"
ASSET_NAME = "UAV-1"
DATA_REF = "data"
RIDS_PATH = pathlib.Path(__file__).parent / "uav_rids.json"


def main() -> None:
    client = NominalClient.from_profile(PROFILE)

    dataset = next(
        (d for d in client.search_datasets(search_text=DATASET_NAME) if d.name == DATASET_NAME),
        None,
    )
    if dataset is None:
        dataset = client.create_dataset(
            DATASET_NAME,
            description="Live UAV telemetry for the automated requirements-verification demo.",
            prefix_tree_delimiter=".",
            properties={"verification_campaign": "rtx-uav"},
        )
        print(f"created dataset {dataset.rid}")
    else:
        print(f"found dataset {dataset.rid}")

    asset = next(
        (a for a in client.search_assets(search_text=ASSET_NAME) if a.name == ASSET_NAME), None
    )
    if asset is None:
        asset = client.create_asset(
            ASSET_NAME,
            description="UAV test article for the automated requirements-verification campaign.",
            properties={"verification_campaign": "rtx-uav"},
            labels=["verification", "uav"],
        )
        print(f"created asset {asset.rid}")
    else:
        print(f"found asset {asset.rid}")

    scopes = {s.data_scope_name for s in asset.list_data_scopes()}
    if DATA_REF not in scopes:
        asset.add_dataset(DATA_REF, dataset)
        print(f"attached dataset to asset as ref '{DATA_REF}'")
    else:
        print(f"asset already carries ref '{DATA_REF}'")

    RIDS_PATH.write_text(
        json.dumps({"dataset_rid": dataset.rid, "asset_rid": asset.rid}, indent=2)
    )
    print(f"\nwrote {RIDS_PATH}")
    print(f"asset: {WORKSPACE_URL}/assets/{asset.rid}")


if __name__ == "__main__":
    main()
