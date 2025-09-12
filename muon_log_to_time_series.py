#!/usr/bin/env python3
"""
Log file parser for converting timestamped channel data to pandas DataFrame.

Parses log files with format:
[timestamp] {header} {subchannel}:{value} {subchannel}:{value} ...

Creates channel names as:
- {header}.{subchannel} when header exists
- {subchannel} when no header exists

Converts values to numbers when possible, otherwise keeps as strings.
"""

import re
import pandas as pd
from datetime import datetime
from typing import Dict, Union

from nominal.thirdparty.pandas import upload_dataframe
from nominal import get_default_client, NominalClient

# Configuration - change these as needed
PROFILE_NAME = "nominal-demo@muonspace.com"  # Change this to your profile name
# Alternative: Use token and workspace directly
# TOKEN = "your-token-here"
# WORKSPACE_RID = "your-workspace-rid-here"

# Dataset configuration
DATASET_NAME = "Example Muon Log Data (Anish)"  # Name for new dataset (if not using existing)
EXISTING_DATASET_RID = None  # Set to dataset RID to ingest to existing dataset


def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse timestamp string to datetime object."""
    return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')


def try_convert_to_number(value_str: str) -> Union[int, float, str]:
    """Try to convert string to number, return original string if conversion fails."""
    value_str = value_str.strip()
    
    for converter in [int, float]:
        try:
            return converter(value_str)
        except ValueError:
            pass
    
    if value_str.startswith(('0x', '0X')):
        try:
            return int(value_str, 16)
        except ValueError:
            pass
    
    if value_str.startswith(('0b', '0B')):
        try:
            return int(value_str, 2)
        except ValueError:
            pass
    
    return value_str


def parse_log_line(line: str) -> tuple[datetime, Dict[str, Union[int, float, str]]]:
    """Parse a log line and extract timestamp + channel data."""
    if not line.strip():
        return None, {}
    
    timestamp_match = re.match(r'\[([^\]]+)\]', line)
    if not timestamp_match:
        return None, {}
    
    timestamp = parse_timestamp(timestamp_match.group(1))
    parts = line[timestamp_match.end():].strip().split()
    
    if not parts:
        return timestamp, {}
    
    channel_data = {}
    has_header = len(parts) > 1 and ':' not in parts[0] and ':' in parts[1]
    
    for part in parts[1:] if has_header else parts:
        if ':' in part:
            subchannel, value = part.split(':', 1)
            channel_name = f"{parts[0]}.{subchannel.strip()}" if has_header else subchannel.strip()
            channel_data[channel_name] = try_convert_to_number(value)
    
    return timestamp, channel_data


def parse_log_file(file_path: str) -> pd.DataFrame:
    """Parse log file into a pandas DataFrame."""
    all_data = []
    all_channels = set()
    
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            timestamp, channel_data = parse_log_line(line)
            if timestamp is not None and channel_data:
                all_data.append((timestamp, channel_data))
                all_channels.update(channel_data.keys())
    
    if not all_data:
        raise ValueError("No valid data found in log file")
    
    all_channels = sorted(all_channels)
    rows = [{'timestamp': timestamp, **{ch: channel_data.get(ch, None) for ch in all_channels}} 
            for timestamp, channel_data in all_data]
    
    df = pd.DataFrame(rows)
    df.set_index('timestamp', inplace=True)
    return df


def upload_to_nominal(df: pd.DataFrame, dataset_name: str = "Example Muon Log Data (Anish)"):
    """Upload the DataFrame to Nominal."""
    # Use specified profile or fall back to default
    if PROFILE_NAME != "your-profile-name":
        client = NominalClient.from_profile(profile=PROFILE_NAME)
    else:
        client = get_default_client()
    
    df_upload = df.reset_index()
    
    if EXISTING_DATASET_RID:
        # Ingest to existing dataset
        dataset = client.get_dataset(rid=EXISTING_DATASET_RID)
        dataset.add_tabular_data(
            path=None,  # We'll use the DataFrame directly
            df=df_upload,
            timestamp_column="timestamp",
            timestamp_type="iso_8601"
        )
        return dataset
    else:
        # Create new dataset
        return upload_dataframe(
            client=client,
            df=df_upload,
            name=dataset_name,
            timestamp_column="timestamp",
            timestamp_type="iso_8601",
            channel_name_delimiter="."
        )


def main():
    """Parse log file and upload to Nominal."""
    LOG_FILE_PATH = "/Users/ashenoy/Downloads/25070002.log"
    
    print(f"Parsing {LOG_FILE_PATH}...")
    df = parse_log_file(LOG_FILE_PATH)
    
    print(f"Got {len(df)} rows with {len(df.columns)} channels")
    print(f"Time range: {df.index.min()} to {df.index.max()}")
    
    if EXISTING_DATASET_RID:
        print(f"\nIngesting to existing dataset: {EXISTING_DATASET_RID}")
    else:
        print(f"\nCreating new dataset: {DATASET_NAME}")
    
    print(f"Uploading to Nominal...")
    dataset = upload_to_nominal(df, DATASET_NAME)
    
    if dataset:
        print(f"Done! Dataset RID: {dataset.rid}")
    else:
        print("Upload failed")
    
    return df


if __name__ == "__main__":
    main()
