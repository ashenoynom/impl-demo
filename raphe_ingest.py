#!/usr/bin/env python3
import os
import tempfile
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from nominal import NominalClient
from nominal.config import NominalConfig

# --- CONFIGURATION ---
client = NominalClient.from_profile(profile="raphe-demo@allnominal.com")
DATA_FOLDER = "/Users/ashenoy/Downloads/Raphe"
USE_PARALLEL = True  # 👈 Set to True to ingest in parallel

# --- INGESTION LOGIC ---
def process_and_upload_csv(filename: str, dataset):
    filepath = os.path.join(DATA_FOLDER, filename)
    try:
        df = pd.read_csv(filepath)

        # Clean export artifact
        first_col_name = df.columns[0]
        if df[first_col_name].nunique() == 1 and df[first_col_name].iloc[0] == 0:
            df = df.drop(columns=[first_col_name])

        # Check for mavpackettype
        if "mavpackettype" not in df.columns:
            return f"⚠️ Skipping {filename}: no 'mavpackettype'."

        mav_type = df["mavpackettype"].iloc[0]
        df = df.rename(columns={col: f"{mav_type}.{col}" for col in df.columns})
        df = df.rename(columns={f"{mav_type}.TimeUS": "time_us"})

        # Write temp CSV
        temp_path = os.path.join(tempfile.gettempdir(), filename)
        df.to_csv(temp_path, index=False)

        # Upload
        dataset.add_tabular_data(
            path=temp_path,
            timestamp_column="time_us",
            timestamp_type="epoch_microseconds",
            # tag_columns={"mavpackettype": f"{mav_type}.mavpackettype"}
        )

        return f"✅ Ingested {filename} with prefix '{mav_type}.'"
    except Exception as e:
        return f"❌ Error processing {filename}: {str(e)}"

# --- SERIAL INGESTION ---
def ingest_all_csvs_serial(dataset):
    csv_files = [f for f in os.listdir(DATA_FOLDER) if f.endswith(".csv")]
    for filename in csv_files:
        result = process_and_upload_csv(filename, dataset)
        print(result)

# --- PARALLEL INGESTION ---
def ingest_all_csvs_parallel(dataset, max_workers=8):
    csv_files = [f for f in os.listdir(DATA_FOLDER) if f.endswith(".csv")]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_and_upload_csv, f, dataset): f for f in csv_files
        }

        for future in as_completed(futures):
            print(future.result())

# --- DATASET LOOKUP ---
def find_dataset_rid(search_text: str, token: str) -> str | None:
    url = "https://api.gov.nominal.io/api/catalog/v1/search-datasets-v2"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "query": {
            "type": "searchText",
            "searchText": search_text
        },
        "sortOptions": {
            "isDescending": True,
            "field": "INGEST_DATE"
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"API error: {response.status_code}")
        print(response.text)
        return None

    data = response.json()
    for result in data.get("results", []):
        if result.get("name") == search_text:
            return result.get("rid")
    return None

# --- MAIN SCRIPT START ---
config = NominalConfig.from_yaml()
token = config.get_profile(name="raphe-demo@allnominal.com").token
dataset_name = "Raphe Example Data"

rid = find_dataset_rid(dataset_name, token)
if rid:
    print(f"✅ Found dataset RID: {rid}")
    dataset = client.get_dataset(rid=rid)
else:
    print("⚙️ No match found. Creating dataset...")
    dataset = client.create_dataset(name=dataset_name, prefix_tree_delimiter=".")

# --- INGEST ---
if USE_PARALLEL:
    print("🚀 Ingesting in parallel...")
    ingest_all_csvs_parallel(dataset)
else:
    print("🐢 Ingesting serially for debugging...")
    ingest_all_csvs_serial(dataset)
