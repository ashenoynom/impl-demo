import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from nominal.core import NominalClient
from nominal.core.filetype import FileTypes
from nominal.thirdparty.pandas import datasource_to_dataframe

# ========== CONFIGURATION ==========
### INPUTS ###
SOURCE_FOLDER = Path("/Users/ashenoy/Code/shift-suv-samples")
token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2F1dGguZ292Lm5vbWluYWwuaW8iLCJzdWIiOiJyaS5hdXRobi5jZXJ1bGVhbi1zdGFnaW5nLnVzZXIuZGRlN2MwYzUtYzhkYy00YWRmLTk0NzMtN2RkNjYzMmU2MmZkIiwibm9taW5hbCI6eyJ1c2VyX3V1aWQiOiJkZGU3YzBjNS1jOGRjLTRhZGYtOTQ3My03ZGQ2NjMyZTYyZmQiLCJvcmdhbml6YXRpb25fdXVpZCI6IjkxNmE2Y2YyLTY1NWEtNGJjZC1iMDNkLTkxNDMyYjQyNGEwNyJ9LCJleHAiOjE3NTI2MTU2MTAsImF1ZCI6Imh0dHBzOi8vYXBpLmdvdi5ub21pbmFsLmlvIn0.j_riAqgaj1Kf4Gk9bdkROnBIjK_B4KegEw43HJj6YUnYZE8iNlsD5TFivXVzJ6xbd3cAV8mfU6WONQODxvr7bWQFF6tjSB5o9BYc76N5WEHWZtfSk1vFQb1gcxm07igzwXx2h-S4lEBT7XhGWZLbFbc8Pzs7wRnudcXHkPrSv2M3_wTUyBM7_Pdb8WBUCXI2OSjt0LBRfAGhjwlRGoodqbW04di7pDErQXsMyUbePnjRg425hN96pTvNJNX3Ndw67KY3WIwdPJlOFfM6C9jREm9lvpGD5dbF4yMdhXNGFAq7Ur0KqBt-aBLqXqOTq9LsXf955D1IM2nSLpqsWqg4Pg"
workspace_rid="ri.security.cerulean-staging.workspace.ce2af5a3-01d2-4da6-9113-70b343683759"

client = NominalClient.from_token(token=token, workspace_rid=workspace_rid)

MAX_WORKERS = os.cpu_count() or 4
SEQUENTIAL = True  # <<<< SET TO FALSE TO ENABLE PARALLEL MODE >>>>

# ========== CORE LOGIC ==========

def upload_attachment(path, run_name):
    try:
        with open(path, "rb") as f:
            attachment = client.create_attachment_from_io(
                attachment=f,
                name=path.name,
                file_type=FileTypes.BINARY,
                description=f"Reuploaded attachment for {run_name}: {path.name}",
            )
        print(f"✅ Uploaded {path.name} for {run_name}")
        return attachment
    except Exception as e:
        print(f"❌ Failed to upload {path} for {run_name}: {e}")
        return None

def process_run(run):
    run_name = run.name
    print(f"\n--- Processing run: {run_name} ---")

    # 1️⃣ List and remove current attachments
    current_attachments = run.list_attachments()
    if current_attachments:
        run.remove_attachments(current_attachments)
        print(f"Removed {len(current_attachments)} old attachments from {run_name}.")
    else:
        print(f"No attachments found to remove on {run_name}.")

    # 2️⃣ Locate local files for this run
    run_folder = SOURCE_FOLDER / run_name
    if not run_folder.exists():
        print(f"⚠️ Source folder {run_folder} does not exist, skipping.")
        return

    attachment_paths = [
        run_folder / f
        for f in os.listdir(run_folder)
        if f.endswith((".stl", ".vtp", ".png"))
    ]

    viz_folder = run_folder / "viz"
    if viz_folder.exists():
        attachment_paths.extend([
            viz_folder / f
            for f in os.listdir(viz_folder)
            if f.endswith(".png")
        ])

    if not attachment_paths:
        print(f"⚠️ No attachments found in {run_folder} or viz/ for {run_name}, skipping.")
        return

    # 3️⃣ Upload attachments (sequential or parallel)
    new_attachments = []
    if SEQUENTIAL:
        for path in attachment_paths:
            attachment = upload_attachment(path, run_name)
            if attachment is not None:
                new_attachments.append(attachment)
    else:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_path = {
                executor.submit(upload_attachment, path, run_name): path
                for path in attachment_paths
            }
            for future in as_completed(future_to_path):
                result = future.result()
                if result is not None:
                    new_attachments.append(result)

    # 4️⃣ Add attachments to the run
    if new_attachments:
        try:
            run.add_attachments(new_attachments)
            print(f"✅ Added {len(new_attachments)} attachments to {run_name}.")
        except Exception as e:
            print(f"❌ Failed to add attachments to {run_name}: {e}")
    else:
        print(f"⚠️ No attachments uploaded for {run_name}, skipping addition.")

def pull_pandas_data(run_search: str):
    run = client.search_runs(name_substring=run_search)[0]
    dataset = run.list_datasets()[0][1]
    df = datasource_to_dataframe(datasource=dataset)
    return print(df.head())


def main():
    runs = client.search_runs()
    print(f"Found {len(runs)} runs to process.")

    if SEQUENTIAL:
        for run in runs:
            process_run(run)
    else:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, 8)) as executor:
            futures = [executor.submit(process_run, run) for run in runs]
            for future in as_completed(futures):
                future.result()  # propagate exceptions

if __name__ == "__main__":
    run_search = input("Enter run name: ")
    pull_pandas_data(run_search)

