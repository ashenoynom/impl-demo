import os
from pathlib import Path
import pandas as pd
from tqdm import tqdm
from datetime import timedelta

from nominal.core import NominalClient
from nominal.thirdparty.pandas import channel_to_series
from nominal.core import EventType

# ========= CONFIG =========
source_data_path = "/Users/ashenoy/Downloads/Orbital Operations"
TIMESTAMP_COLUMN = "timestamp"
TIMESTAMP_TYPE = "unix_ns"          # nanoseconds since Unix epoch
RUN_NAME_PREFIX = "Run "            # runs will be named "Run 1", "Run 2", ...
ARCHIVE_NAME_SUBSTRING = "Run "     # set to None to archive ALL runs
DATASET_NAME = "Revel Data"
DATASET_DESC = "Igniter test stand Revel data"
# ==========================

data_folder = Path(source_data_path)
all_parquets = sorted(data_folder.glob("*.parquet"))  # stable order for run numbering

client = NominalClient.from_profile(profile="orbital-ops-demo@allnominal.com")
dataset = client.create_dataset(name=DATASET_NAME, description=DATASET_DESC)
# Or reuse an existing dataset:
# dataset = client.get_dataset(rid="ri.catalog.cerulean-staging.dataset....")

# -------- Phase 0: Archive runs (serial) --------
def archive_runs(*, name_substring=ARCHIVE_NAME_SUBSTRING, start=None, end=None, labels=None, properties=None, dry_run=False):
    runs = client.search_runs(start=start, end=end, name_substring=name_substring, labels=labels, properties=properties)
    print(f"[Archive] Found {len(runs)} run(s) to archive.")
    if dry_run:
        for r in runs[:10]:
            print(f"[DRY RUN] Would archive: {r.name} ({r.rid})")
        if len(runs) > 10:
            print(f"...and {len(runs) - 10} more.")
        return
    for r in tqdm(runs, desc="Archiving runs"):
        r.archive()
    print("✅ Archiving complete.\n")

# -------- Phase 1: Upload Parquets (serial) --------
def upload_all_parquets_serial(parquet_paths):
    print(f"[Upload] Found {len(parquet_paths)} parquet file(s).")
    uploaded = 0
    for pq in tqdm(parquet_paths, desc="Uploading parquets"):
        dataset.add_tabular_data(
            path=str(pq),
            timestamp_column=TIMESTAMP_COLUMN,
            timestamp_type=TIMESTAMP_TYPE,
        )
        uploaded += 1
    print(f"✅ Uploaded {uploaded} parquet file(s).\n")

# -------- Phase 2: Create Runs (serial) --------
def create_runs_for_parquets_serial(parquet_paths):
    print(f"[Runs] Creating runs for {len(parquet_paths)} parquet file(s).")
    for idx, pq in enumerate(parquet_paths, start=1):
        # Read only the timestamp column; use min/max to be robust to unsorted files
        ts = pd.read_parquet(pq, columns=[TIMESTAMP_COLUMN])[TIMESTAMP_COLUMN]
        start_ns = int(ts.min())
        end_ns = int(ts.max())

        run_name = f"{RUN_NAME_PREFIX}{idx}"
        client.create_run(
            name=run_name,
            start=start_ns,  # unix ns
            end=end_ns,
            description=f"Auto-run for {Path(pq).name}",
            asset="ri.scout.cerulean-staging.asset.2aca4b67-0267-482f-86d0-9027a013da28"
        )
    print("✅ Run creation complete.\n")

# -------- Phase 3: Create T0 Events (serial) --------
def create_t0_events_for_runs(*, dataset_rid: str, asset_rid: str, dry_run=False):
    """
    Create T0 events when SV_H105 channel first hits value 1.
    
    Args:
        dataset_rid: The RID of the dataset containing the SV_H105 channel
        asset_rid: The RID of the asset to add events to
        dry_run: If True, only print what would be done without actually creating events
    """
    # Get the dataset and asset
    dataset = client.get_dataset(dataset_rid)
    print(f"[T0 Events] Using dataset: {dataset.name} ({dataset.rid})")
    print(f"[T0 Events] Using asset RID: {asset_rid}")
    
    try:
        # Get the SV_H105 channel from the dataset
        channel = dataset.get_channel(name="SV_H105")
        print(f"[T0 Events] Found SV_H105 channel: {channel.name}")
        
        # Convert channel to pandas series using the imported function
        sv_h105_series = channel_to_series(channel)
        print(f"[T0 Events] Channel data shape: {sv_h105_series.shape}")
        print(f"[T0 Events] Channel data range: {sv_h105_series.index.min()} to {sv_h105_series.index.max()}")
        
        # Find transitions from 0 to 1 (rising edges)
        # Shift the series by 1 to compare current value with previous value
        previous_values = sv_h105_series.shift(1)
        rising_edges = (sv_h105_series == 1) & (previous_values == 0)
        t0_indices = sv_h105_series[rising_edges].index
        
        if len(t0_indices) == 0:
            print("⚠️ No rising edges (0->1 transitions) found in SV_H105 channel data")
            return
        
        print(f"[T0 Events] Found {len(t0_indices)} rising edges (0->1 transitions) in SV_H105")
        
        if dry_run:
            print("[DRY RUN] Would create T0 events at the following timestamps:")
            for i, timestamp in enumerate(t0_indices[:10]):
                print(f"  - {timestamp}")
            if len(t0_indices) > 10:
                print(f"  ...and {len(t0_indices) - 10} more.")
            return
        
        # Create T0 events for each occurrence
        events_created = 0
        for timestamp in tqdm(t0_indices, desc="Creating T0 events"):
            try:
                event = client.create_event(
                    name="T0",
                    type=EventType.INFO,
                    start=timestamp,
                    duration=timedelta(),  # Default timedelta (0 duration)
                    assets=[asset_rid]
                )
                events_created += 1
                
            except Exception as e:
                print(f"❌ Error creating event at {timestamp}: {e}")
        
        print(f"✅ T0 event creation complete. Created {events_created} events.\n")
        
    except Exception as e:
        print(f"❌ Error processing SV_H105 channel: {e}")
        print("Make sure the channel name 'SV_H105' exists in the dataset.")

if __name__ == "__main__":
    # Phase 0
    # archive_runs(dry_run=False)  # set to True to preview

    # Phase 1
    # upload_all_parquets_serial(all_parquets)

    # Phase 2
    # create_runs_for_parquets_serial(all_parquets)
    
    # Phase 3 - Uncomment and set your dataset and asset RIDs
    create_t0_events_for_runs(
        dataset_rid="ri.catalog.cerulean-staging.dataset.ae7277f3-0c76-4d6b-be96-1c516d77b229",
        asset_rid="ri.scout.cerulean-staging.asset.2aca4b67-0267-482f-86d0-9027a013da28",
        dry_run=False  # set to False to actually create events
    )
