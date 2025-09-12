import os
import pandas as pd
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from nominal.core import NominalClient
from nominal.core.filetype import FileTypes

# ========== CONFIGURATION ==========
### INPUTS ###
BASE_DIR = "/Users/ashenoy/Code/shift-suv-samples"
token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguZ292Lm5vbWluYWwuaW8iLCJzdWIiOiJyaS5hdXRobi5jZXJ1bGVhbi1zdGFnaW5nLnVzZXIuZGRlN2MwYzUtYzhkYy00YWRmLTk0NzMtN2RkNjYzMmU2MmZkIiwibm9taW5hbCI6eyJ1c2VyX3V1aWQiOiJkZGU3YzBjNS1jOGRjLTRhZGYtOTQ3My03ZGQ2NjMyZTYyZmQiLCJvcmdhbml6YXRpb25fdXVpZCI6IjkxNmE2Y2YyLTY1NWEtNGJjZC1iMDNkLTkxNDMyYjQyNGEwNyJ9LCJleHAiOjE3NTI0NTMwMjIsImF1ZCI6Imh0dHBzOi8vYXBpLmdvdi5ub21pbmFsLmlvIn0.jbMwCHi_1cVyRcgDc8P-N6znzXiJAAWBAXbTzLGhjFUyn50nGZrsJwCCHgl3MUng5jEDrTbyJQwCcIxCdhEwVEVO92nuBxNfZbD0VxLmx36Xa5wPexdwTZLBafmMYuhuEWElY7QQY7FNlXmjAchMQZBfhyELjuMwY_wn1zNqcw2ebRMcdKiRKjUelLsdTTnp2GMUp0pMVfabGNN7VZPB4BRYUzB0FyOT1Eawaf4l-sOZbxIlfnPdA6JL5H5tlk3Jq2jzKc7LXt48vjYg1NdY_KKPBVn_HEjCTsEHaSLdnUXG-XxCocFjbAoD15XRdWu3PFdq1pJ7IX1xrhEqRrtGRQ"
workspace_rid="ri.security.cerulean-staging.workspace.ce2af5a3-01d2-4da6-9113-70b343683759"
##############

client = NominalClient.from_token(token=token, workspace_rid=workspace_rid)

def process_run(run_path, runs_to_attach):
    run_name = os.path.basename(run_path)
    print(f"Processing {run_name}...")

    # 0. Check if CSVs are present
    csv_files = [f for f in os.listdir(run_path) if f.endswith(".csv")]
    if not csv_files:
        print(f"Skipping {run_name}: No .csv files found in {run_path}")
        return runs_to_attach

    # 1. Create Dataset
    dataset = client.create_dataset(
        name=run_name,
        description=f"Shift SUV CFD ingestion for {run_name}",
        labels=["cfd", "shift-suv"],
    )

    temp_dir = tempfile.mkdtemp()

    try:
        # 2. Process each CSV
        csv_files = [f for f in os.listdir(run_path) if f.endswith(".csv")]
        max_row_count = 0

        for csv_file in csv_files:
            csv_path = os.path.join(run_path, csv_file)
            df = pd.read_csv(csv_path)

            # Add synthetic timestamp column
            df.insert(0, "timestamp", pd.Series(range(len(df)), dtype="int64"))
            max_row_count = max(max_row_count, len(df))

            # Save to temporary CSV for ingestion
            temp_csv_path = os.path.join(temp_dir, csv_file)
            df.to_csv(temp_csv_path, index=False)

            # Ingest using add_tabular_data
            dataset.add_tabular_data(
                path=temp_csv_path,
                timestamp_column="timestamp",
                timestamp_type="epoch_seconds",
            )

        # 3. Collect attachment file paths
        attachment_paths = [
            os.path.join(run_path, f)
            for f in os.listdir(run_path)
            if f.endswith((".stl", ".vtp", ".png"))
        ]

        viz_dir = os.path.join(run_path, "viz")
        if os.path.exists(viz_dir):
            attachment_paths.extend([
                os.path.join(viz_dir, f)
                for f in os.listdir(viz_dir)
                if f.endswith(".png")
            ])

        # 4. Create Run with accurate timing (without attachments)
        timestamps = df["timestamp"]
        start_time = datetime.fromtimestamp(timestamps.min(), tz=timezone.utc)
        end_time = datetime.fromtimestamp(timestamps.max(), tz=timezone.utc)


        run = client.create_run(
            name=run_name,
            start=start_time,
            end=end_time,
            description=f"Luminary Cloud Shift SUV CFD data  {run_name}"
        )

        # 5. Link dataset to run
        run.add_dataset(ref_name="CFD Data", dataset=dataset)

        print(f"Finished data upload for {run_name}")

        # 6. Collect attachment upload for later upload
        runs_to_attach.append({
        "run_rid": run.rid,
        "run_name": run_name,
        "attachment_paths": attachment_paths,
        })

        print(f"Collected attachment info for {run_name}")

    finally:
        # Clean up temporary files
        shutil.rmtree(temp_dir)
    
    return runs_to_attach

def main():
    run_paths = [
        os.path.join(BASE_DIR, d)
        for d in os.listdir(BASE_DIR)
        if d.startswith("RUN_") and os.path.isdir(os.path.join(BASE_DIR, d))
    ]

    # Sequential
    runs_to_attach = []
    for run_path in run_paths:
        runs_to_attach = process_run(run_path, runs_to_attach)
    
    for item in runs_to_attach:
        run = client.get_run(item["run_rid"])
        attachments = []
        for path in item["attachment_paths"]:
            with open(path, "rb") as f:
                attachment = client.create_attachment_from_io(
                    attachment=f,
                    name=os.path.basename(path),
                    file_type=FileTypes.BINARY,
                    description=f"Attachment for {item['run_name']}: {os.path.basename(path)}",
                )
                attachments.append(attachment)
                print(f"Uploaded attachment {os.path.basename(path)} for run {item['run_name']}")
        run.add_attachments(attachments)
        print(f"Added {len(attachments)} attachments to run {item['run_name']}")

if __name__ == "__main__":
    main()
