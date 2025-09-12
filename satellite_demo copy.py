import os
import gzip
import shutil
from datetime import datetime
import nominal as nm
from nominal.core import NominalClient

import pandas as pd
from pathlib import Path

# Optional: use tqdm for a clean progress bar
from tqdm import tqdm

# Source data folder
source_data_path = "/Users/ashenoy/Downloads/satellite_data"
data_folder = Path("/Users/ashenoy/Downloads/satellite_data")

# Load metadata.csv into a DataFrame for easy lookup
metadata_df = pd.read_csv(os.path.join(source_data_path, "metadata.csv"), sep="\t")

# Create lookup dictionaries
desc_lookup = dict(zip(metadata_df["param_name"], metadata_df["param_description"]))
unit_lookup = dict(zip(metadata_df["param_name"], metadata_df["param_unit"]))

# Gather all channels for processing
all_channels = [p for p in data_folder.iterdir() if p.is_dir()]
total_channels = len(all_channels)

print(f"Found {total_channels} channels to upload.")

# Create Nominal Client and dataset
client = NominalClient.from_token("eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguZ292Lm5vbWluYWwuaW8iLCJzdWIiOiJyaS5hdXRobi5jZXJ1bGVhbi1zdGFnaW5nLnVzZXIuMDgyNzQ3NjQtOGQ1Ni00MWVmLTk4ZGItYTA0YzNiM2Q1OGVhIiwibm9taW5hbCI6eyJ1c2VyX3V1aWQiOiIwODI3NDc2NC04ZDU2LTQxZWYtOThkYi1hMDRjM2IzZDU4ZWEiLCJvcmdhbml6YXRpb25fdXVpZCI6Ijc5YzJjZGQxLTRjY2QtNDI4OC1iMDZiLTI0ZTkwMmE2YjNhZiJ9LCJleHAiOjE3NTE0NzEyNjEsImF1ZCI6Imh0dHBzOi8vYXBpLmdvdi5ub21pbmFsLmlvIn0.I9kN3iKdObLcAk6HdfCc-dvkeYLGUpCWG4CzQkckJAqZYpVnIRHS5u7C3gYaHeoy6bH7vZnwkOZdjkeDW_ijKmoGwLYOTFEUMWn0gawkPYtCFTEYQ1Itdz8z6l1muH9DRNcSgJ04TqVtAqEC2qzcvtZvBUb4Kn7DSkO4SGE5auFfVeiTh6u-Zv-gafLn1H7UBNP5tq1cARdYgrIZ0FnxD445DomKNgPA7AfJPOCuLxBJK76AvsNJUVj3YP-a8oMIQi4Safq4PQgz2qOSxoV2f9E-G1gkN8UsURuzb-Yj8foEvSseOkc9SoZaTV-9mXU_PNrj8yZAG9zdOq58_h1OuA",
                                  workspace_rid="ri.security.cerulean-staging.workspace.0e49de18-bc16-4269-ac70-fab9b274de1e")

dataset = client.create_dataset(
                        name='GOCE Dataset',
                        description="GOCE Satellite Telemetry Dataset",
                        )

# Use tqdm for a progress bar
for idx, channel_folder in enumerate(tqdm(all_channels, desc="Uploading channels", unit="channel")):
    channel_name = channel_folder.name
    parquet_file = channel_folder / f"{channel_name}_raw.parquet"
    temp_parquet = None

    # Log progress and current channel
    print(f"\n[{idx + 1}/{total_channels}] Processing {channel_name}")

    # Check if the file containing data of interest is present
    if not parquet_file.exists():
        print(f"⚠️ Skipping {channel_name}: parquet file not found at {parquet_file}")
        continue
    
    # Make sure temp_parquet is always defined so there's no errors later
    if temp_parquet and Path(temp_parquet).exists():
        Path(temp_parquet).unlink()

    try:
        # Load parquet and clean + convert timestamps
        df = pd.read_parquet(parquet_file)
        df = df.reset_index()

        # Remove "(Eastern Daylight Time)" and similar strings for parsing
        # df["timestamp"] = df["timestamp"].str.replace(r" \(.*\)", "", regex=True)

        # Convert to datetime, resulting in datetime64[ns, tz] dtype
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        # Change value column to channel name
        df = df.rename(columns={"value": channel_name})

        # Save back to temporary parquet for ingestion
        temp_parquet = f"{channel_name}_nominal_ready.parquet"
        df.to_parquet(temp_parquet, index=False)

        # Upload to Nominal
        dataset.add_tabular_data(
            path=temp_parquet,
            timestamp_column="timestamp",
            timestamp_type="iso_8601",
        )
        print(f"✅ Uploaded {channel_name} to Nominal.")

        # Retrieve the channel and update description and unit
        channel = dataset.get_channel(name=channel_name)
        description = desc_lookup.get(channel_name)
        unit = unit_lookup.get(channel_name)

        channel.update(description=description, unit=unit)
        print(f"✅ Updated {channel_name} with description='{description}' and unit='{unit}'.")

    except Exception as e:
        print(f"❌ Failed to upload or update {channel_name}: {e}")

    finally:
        # Clean up temporary parquet
        if Path(temp_parquet).exists():
            Path(temp_parquet).unlink()

# Completion log
print("\n✅ All channels processed and uploaded to Nominal.")
