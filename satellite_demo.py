import os
from pathlib import Path
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

import nominal as nm
from nominal.core import NominalClient

# ========== CONFIGURATION ==========
### INPUTS ###
source_data_path = "/Users/ashenoy/Downloads/satellite_data"
token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguZ292Lm5vbWluYWwuaW8iLCJzdWIiOiJyaS5hdXRobi5jZXJ1bGVhbi1zdGFnaW5nLnVzZXIuMDgyNzQ3NjQtOGQ1Ni00MWVmLTk4ZGItYTA0YzNiM2Q1OGVhIiwibm9taW5hbCI6eyJ1c2VyX3V1aWQiOiIwODI3NDc2NC04ZDU2LTQxZWYtOThkYi1hMDRjM2IzZDU4ZWEiLCJvcmdhbml6YXRpb25fdXVpZCI6Ijc5YzJjZGQxLTRjY2QtNDI4OC1iMDZiLTI0ZTkwMmE2YjNhZiJ9LCJleHAiOjE3NTE0NzEyNjEsImF1ZCI6Imh0dHBzOi8vYXBpLmdvdi5ub21pbmFsLmlvIn0.I9kN3iKdObLcAk6HdfCc-dvkeYLGUpCWG4CzQkckJAqZYpVnIRHS5u7C3gYaHeoy6bH7vZnwkOZdjkeDW_ijKmoGwLYOTFEUMWn0gawkPYtCFTEYQ1Itdz8z6l1muH9DRNcSgJ04TqVtAqEC2qzcvtZvBUb4Kn7DSkO4SGE5auFfVeiTh6u-Zv-gafLn1H7UBNP5tq1cARdYgrIZ0FnxD445DomKNgPA7AfJPOCuLxBJK76AvsNJUVj3YP-a8oMIQi4Safq4PQgz2qOSxoV2f9E-G1gkN8UsURuzb-Yj8foEvSseOkc9SoZaTV-9mXU_PNrj8yZAG9zdOq58_h1OuA"
workspace_rid="ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e"
##############

data_folder = Path(source_data_path)

metadata_df = pd.read_csv(os.path.join(source_data_path, "metadata.csv"), sep="\t")
desc_lookup = dict(zip(metadata_df["param_name"], metadata_df.apply(lambda row: f"{row['param_description']} - {row['param_description_long']}", axis=1)))
unit_lookup = dict(zip(metadata_df["param_name"], metadata_df["param_unit"]))

all_channels = [p for p in data_folder.iterdir() if p.is_dir()]
total_channels = len(all_channels)
print(f"Found {total_channels} channels to upload.")

client = NominalClient.from_token(token=token, workspace_rid=workspace_rid)
dataset = client.create_dataset(
    name="GOCE Dataset",
    description="GOCE Satellite Telemetry Dataset",
)
dataset = client.get_dataset(rid="ri.catalog.cerulean-staging.dataset.da4078dd-5565-466f-8b72-8c3ffa962373")

# ========== PHASE 1: PARALLEL UPLOAD ==========

def upload_channel(channel_folder: Path):
    channel_name = channel_folder.name
    parquet_file = channel_folder / f"{channel_name}_raw.parquet"

    if not parquet_file.exists():
        return f"⚠️ Skipped {channel_name}: parquet file not found at {parquet_file}"

    temp_parquet = f"{channel_name}_nominal_ready.parquet"

    try:
        df = pd.read_parquet(parquet_file)
        df = df.reset_index()
        df = df.rename(columns={"value": channel_name})
        df.to_parquet(temp_parquet, index=False)

        dataset.add_tabular_data(
            path=temp_parquet,
            timestamp_column="timestamp",
            timestamp_type="iso_8601",
        )

        return f"✅ Uploaded {channel_name} to Nominal."
    except Exception as e:
        return f"❌ Failed to upload {channel_name}: {e}"
    finally:
        if Path(temp_parquet).exists():
            Path(temp_parquet).unlink()

def parallel_upload():
    # Use ThreadPoolExecutor for parallel uploads
    max_workers = min(8, os.cpu_count() or 4)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(upload_channel, channel_folder) for channel_folder in all_channels]
        for future in tqdm(as_completed(futures), total=len(futures), desc="Uploading channels"):
            result = future.result()
            print(result)
            results.append(result)

    print("\n✅ Phase 1 complete: All channels uploaded.\n")
    print("Waiting for dataset indexing to complete before metadata update...")
    time.sleep(30)  # adjust based on dataset size

# ========== PHASE 2: METADATA UPDATE ==========
def metadata_update():
    # Sleep to allow dataset indexing to catch up

    for channel_name in tqdm(metadata_df["param_name"], desc="Updating channel metadata"):
        try:
            channel = dataset.get_channel(name=channel_name)
            description = desc_lookup.get(channel_name)
            unit = unit_lookup.get(channel_name)
            channel.update(description=description, unit=unit)
            print(f"✅ Updated {channel_name} with description='{description}' and unit='{unit}'.")
        except Exception as e:
            print(f"❌ Failed to update {channel_name}: {e}")

    print("\n✅ Phase 2 complete: All channel metadata updated.")

def create_asset():
    asset = client.create_asset(
    # Human readable name for the asset
    name="GOCE Satellite",
    # Optional description, useful if you have notes about this glider.
    description=f"The Gravity Field and Steady-State Ocean Circulation Explorer (GOCE) was the first of ESA's Living Planet Programme heavy satellites intended to map in unprecedented detail the Earth's gravity field",
    # Properties which can help us find this asset later.
    # Ideally, you should be able to uniquely identify any physical asset
    # using some combination of these properties.
    properties={
        "platform": "responder",
        "serial_num": asset,
    }
)


# Run Process
# parallel_upload()
metadata_update()