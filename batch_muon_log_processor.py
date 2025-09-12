#!/usr/bin/env python3
"""
Batch processor for Muon log files with folder structure:
header/
    Muon_Charge_Logs_Post_Temp/    # post-test logs
    Muon_Charge_Logs_Pre_Temp/     # pre-test logs  
    Muon_Temp_Cycle_Logs/          # during test logs

Creates individual runs for each battery SN and test type, uploads to Nominal,
saves intermediate CSVs, and executes checklists.
"""

import os
import re
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Union, List, Tuple, Optional
from pathlib import Path
import concurrent.futures
from threading import Lock
import argparse
import json
import gc

from nominal.thirdparty.pandas import upload_dataframe
from nominal import get_default_client, NominalClient

# Configuration
PROFILE_NAME = "nominal-demo@muonspace.com"  # Change this to your profile name
DATASET_NAME_PREFIX = "Muon Battery Logs"  # Prefix for dataset names

# Checklist configuration - set these to your checklist RIDs
PRE_POST_TEST_CHECKLIST_RID = None  # Checklist for pre-test and post-test runs
DURING_TEST_CHECKLIST_RID = None   # Checklist for during-test runs

# Folder structure constants
POST_TEST_FOLDER = "Muon_Charge_Logs_Post_Temp"
PRE_TEST_FOLDER = "Muon_Charge_Logs_Pre_Temp"
DURING_TEST_FOLDER = "Muon_Temp_Cycle_Logs"

# Progress tracking
PROGRESS_FILE = "processing_progress.json"

# Thread-safe print lock
print_lock = Lock()

def safe_print(*args, **kwargs):
    """Thread-safe print function."""
    with print_lock:
        print(*args, **kwargs)

def load_progress():
    """Load progress from file."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_progress(progress):
    """Save progress to file."""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)

def is_step_completed(step_name, progress):
    """Check if a step is completed."""
    return progress.get(step_name, {}).get('completed', False)

def mark_step_completed(step_name, progress, data=None):
    """Mark a step as completed."""
    if step_name not in progress:
        progress[step_name] = {}
    progress[step_name]['completed'] = True
    progress[step_name]['timestamp'] = datetime.now().isoformat()
    if data:
        progress[step_name]['data'] = data
    save_progress(progress)

def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse timestamp string to datetime object."""
    return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

def try_convert_to_number(value_str: str) -> Union[int, float, str]:
    """Try to convert string to number, return original string if conversion fails."""
    value_str = value_str.strip()
    
    # Handle special cases that might cause data type conflicts
    if value_str.upper() in ['TRUE', 'FALSE']:
        return value_str.upper()
    
    if value_str.upper() in ['ON', 'OFF']:
        return value_str.upper()
    
    # Try numeric conversion
    for converter in [int, float]:
        try:
            return converter(value_str)
        except ValueError:
            pass
    
    # Handle hex and binary
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

def is_numeric_value(value) -> bool:
    """Check if a value is numeric (int, float, or convertible string)."""
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except ValueError:
            # Try hex and binary
            if value.startswith(('0x', '0X')):
                try:
                    int(value, 16)
                    return True
                except ValueError:
                    pass
            if value.startswith(('0b', '0B')):
                try:
                    int(value, 2)
                    return True
                except ValueError:
                    pass
    return False

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
    """Parse log file into a pandas DataFrame with consistent data types and deduplication."""
    # First pass: collect all channels to know the full schema
    all_channels = set()
    line_count = 0
    
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            line_count += 1
            timestamp, channel_data = parse_log_line(line)
            if timestamp is not None and channel_data:
                all_channels.update(channel_data.keys())
    
    if not all_channels:
        raise ValueError("No valid data found in log file")
    
    all_channels = sorted(all_channels)
    
    # Second pass: process in chunks to avoid memory issues
    CHUNK_SIZE = 10000  # Process 10k lines at a time
    chunk_dfs = []
    
    with open(file_path, 'r', encoding='utf-8') as file:
        chunk_data = []
        chunk_count = 0
        
        for line in file:
            timestamp, channel_data = parse_log_line(line)
            if timestamp is not None and channel_data:
                chunk_data.append((timestamp, channel_data))
                
                # Process chunk when it reaches CHUNK_SIZE
                if len(chunk_data) >= CHUNK_SIZE:
                    chunk_count += 1
                    
                    # Create DataFrame for this chunk
                    chunk_df = create_chunk_dataframe(chunk_data, all_channels)
                    chunk_dfs.append(chunk_df)
                    
                    # Clear chunk data to free memory
                    chunk_data = []
                    gc.collect()
        
        # Process remaining data in final chunk
        if chunk_data:
            chunk_count += 1
            chunk_df = create_chunk_dataframe(chunk_data, all_channels)
            chunk_dfs.append(chunk_df)
    
    # Combine all chunks
    if len(chunk_dfs) == 1:
        df = chunk_dfs[0]
    else:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            df = pd.concat(chunk_dfs, ignore_index=False)
    
    # Clear chunk DataFrames to free memory
    del chunk_dfs
    gc.collect()
    
    # Deduplicate by timestamp - keep the last value for each timestamp
    df = df.groupby(df.index).last()
    
    # Post-process to ensure consistent data types
    for col in df.columns:
        # Filter out non-numeric values for all columns
        non_null_values = df[col].dropna()
        if len(non_null_values) > 0:
            # Check which values are numeric
            numeric_mask = non_null_values.apply(is_numeric_value)
            
            if numeric_mask.all():
                # All values are numeric, convert to numeric type
                try:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                except (ValueError, TypeError):
                    # If conversion fails, keep as string
                    df[col] = df[col].astype('string')
            elif numeric_mask.any():
                # Some values are numeric, some are not - keep only numeric values
                # Set non-numeric values to NaN
                df[col] = df[col].apply(lambda x: x if is_numeric_value(x) else None)
                # Convert to numeric, non-numeric values become NaN
                df[col] = pd.to_numeric(df[col], errors='coerce')
            else:
                # No numeric values, keep as string
                df[col] = df[col].astype('string')
    
    return df

def create_chunk_dataframe(chunk_data: list, all_channels: list) -> pd.DataFrame:
    """Create a DataFrame from a chunk of data."""
    rows = []
    for timestamp, channel_data in chunk_data:
        row = {'timestamp': timestamp}
        for ch in all_channels:
            value = channel_data.get(ch, None)
            row[ch] = value
        rows.append(row)
    
    df = pd.DataFrame(rows)
    df.set_index('timestamp', inplace=True)
    return df

def get_battery_sns(header_folder: str) -> List[str]:
    """Get list of battery serial numbers from the folder structure."""
    battery_sns = set()
    
    for folder_name in [POST_TEST_FOLDER, PRE_TEST_FOLDER, DURING_TEST_FOLDER]:
        folder_path = os.path.join(header_folder, folder_name)
        if os.path.exists(folder_path):
            for file in os.listdir(folder_path):
                if file.endswith('.log'):
                    battery_sn = file[:-4]  # Remove .log extension
                    battery_sns.add(battery_sn)
    
    return sorted(list(battery_sns))

def separate_single_value_channels(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate channels with only one value into a separate DataFrame."""
    time_series_channels = []
    single_value_channels = []
    
    for col in df.columns:
        non_null_values = df[col].dropna()
        if len(non_null_values) <= 1:
            single_value_channels.append(col)
        else:
            time_series_channels.append(col)
    
    # Create time series DataFrame
    time_series_df = df[time_series_channels] if time_series_channels else pd.DataFrame()
    
    # Create single value DataFrame
    single_value_df = pd.DataFrame()
    if single_value_channels:
        # Create a single row with all single-value channels
        single_row = {}
        for col in single_value_channels:
            non_null_values = df[col].dropna()
            if len(non_null_values) > 0:
                single_row[col] = non_null_values.iloc[0]
            else:
                single_row[col] = None
        
        # Use the first timestamp as the timestamp for single values
        if len(df) > 0:
            single_value_df = pd.DataFrame([single_row], index=[df.index[0]])
            # Reset index to make timestamp a column with proper name
            single_value_df = single_value_df.reset_index()
            single_value_df.rename(columns={'index': 'timestamp'}, inplace=True)
        else:
            single_value_df = pd.DataFrame([single_row])
    
    return time_series_df, single_value_df

def process_single_log(battery_sn: str, test_type: str, log_file_path: str, 
                      output_csv_dir: str, client: NominalClient) -> Optional[str]:
    """Process a single log file and create a run in Nominal."""
    try:
        safe_print(f"Processing {battery_sn} - {test_type}...")
        
        # Parse log file
        df = parse_log_file(log_file_path)
        
        # Get start and stop times from the log data
        start_time = df.index.min()
        stop_time = df.index.max()
        
        safe_print(f"Log time range: {start_time} to {stop_time}")
        
        # Separate single-value channels
        time_series_df, single_value_df = separate_single_value_channels(df)
        
        safe_print(f"Time series channels: {len(time_series_df.columns)}")
        safe_print(f"Single value channels: {len(single_value_df.columns)}")
        
        # Save time series CSV (only time series channels)
        csv_filename = f"{battery_sn}_{test_type}.csv"
        csv_path = os.path.join(output_csv_dir, csv_filename)
        time_series_df.to_csv(csv_path)
        safe_print(f"Saved time series CSV: {csv_path}")
        
        # Save single value CSV if there are any (only single value channels)
        if len(single_value_df.columns) > 0:
            single_csv_filename = f"{battery_sn}_{test_type}_single_values.csv"
            single_csv_path = os.path.join(output_csv_dir, single_csv_filename)
            single_value_df.to_csv(single_csv_path)
            safe_print(f"Saved single values CSV: {single_csv_path}")
        
        # Create dataset name
        dataset_name = f"{DATASET_NAME_PREFIX} - {battery_sn} - {test_type}"
        
        # Create dataset and upload data via CSV files
        if len(time_series_df) > 0:
            safe_print(f"🚀 Starting upload to Nominal...")
            safe_print(f"   Dataset name: {dataset_name}")
            safe_print(f"   Time series data: {len(time_series_df)} rows × {len(time_series_df.columns)} channels")
            safe_print(f"   Data size: ~{len(time_series_df) * len(time_series_df.columns) * 8 / 1024 / 1024:.1f} MB")
            
            import time
            start_time_upload = time.time()
            
            # Step 1: Create empty dataset
            safe_print(f"   📊 Creating empty dataset...")
            dataset = client.create_dataset(
                name=dataset_name,
                description=f"Muon log data for battery {battery_sn} - {test_type}",
                prefix_tree_delimiter="."
            )
            safe_print(f"✅ Created dataset: {dataset.rid}")
            safe_print(f"   📊 Dataset RID: {dataset.rid}")
            
            # Step 2: Add time series data from CSV
            safe_print(f"   📤 Adding time series data from CSV...")
            dataset.add_tabular_data(
                path=csv_path,
                timestamp_column="timestamp",
                timestamp_type="iso_8601"
            )
            safe_print(f"✅ Added time series data to dataset: {dataset.rid}")
            
            # Step 3: Add single value data from CSV if it exists
            if len(single_value_df.columns) > 0:
                safe_print(f"   📤 Adding single values from CSV...")
                dataset.add_tabular_data(
                    path=single_csv_path,
                    timestamp_column="timestamp",
                    timestamp_type="iso_8601"
                )
                safe_print(f"✅ Added single values to dataset: {dataset.rid}")
            
            upload_duration = time.time() - start_time_upload
            safe_print(f"   ⏱️  Upload took: {upload_duration:.1f} seconds")
            
            # Step 4: Create a run from the dataset with proper start/stop times
            run_name = f"{battery_sn} - {test_type} - {start_time.strftime('%Y%m%d_%H%M%S')}"
            safe_print(f"   🏃 Creating run: {run_name}")
            safe_print(f"   Time range: {start_time} to {stop_time}")
            
            # Create run with time range from log data (localize to UTC)
            run = client.create_run(
                name=run_name,
                start=start_time.tz_localize('UTC'),
                end=stop_time.tz_localize('UTC'),
                description=f"Run for battery {battery_sn} - {test_type} from {start_time} to {stop_time}"
            )
            
            safe_print(f"✅ Created run {battery_sn} - {test_type}: {run.rid}")
            
            # Step 5: Add dataset to the run
            safe_print(f"   📊 Adding dataset to run...")
            run.add_dataset(
                ref_name="default",  # Logical name for the dataset within the run
                dataset=dataset
            )
            safe_print(f"✅ Added dataset to run: {run.rid}")
            
            safe_print(f"🎉 Upload complete for {battery_sn} - {test_type}!")
            return run.rid
        else:
            safe_print(f"No time series data found for {battery_sn} - {test_type}")
            return None
        
    except Exception as e:
        safe_print(f"Error processing {battery_sn} - {test_type}: {str(e)}")
        return None

def step1_parse_logs(header_folder: str, output_csv_dir: str, progress: dict):
    """Step 1: Parse log files and create CSV files."""
    step_name = "step1_parse_logs"
    
    if is_step_completed(step_name, progress):
        safe_print(f"✅ {step_name} already completed, skipping...")
        return progress[step_name].get('data', {})
    
    safe_print(f"🔄 Starting {step_name}...")
    
    # Get battery serial numbers
    battery_sns = get_battery_sns(header_folder)
    safe_print(f"Found {len(battery_sns)} battery serial numbers: {battery_sns}")
    
    # Create output directory
    os.makedirs(output_csv_dir, exist_ok=True)
    
    # Prepare processing tasks
    tasks = []
    for battery_sn in battery_sns:
        for test_type, folder_name in [
            ("pre_test", PRE_TEST_FOLDER),
            ("post_test", POST_TEST_FOLDER), 
            ("during_test", DURING_TEST_FOLDER)
        ]:
            log_file_path = os.path.join(header_folder, folder_name, f"{battery_sn}.log")
            if os.path.exists(log_file_path):
                tasks.append((battery_sn, test_type, log_file_path))
            else:
                safe_print(f"Warning: Log file not found: {log_file_path}")
    
    safe_print(f"Processing {len(tasks)} log files...")
    
    # Process files and create CSVs sequentially
    processed_files = {}
    for i, (battery_sn, test_type, log_file_path) in enumerate(tasks, 1):
        safe_print(f"Processing {i}/{len(tasks)}: {battery_sn} - {test_type}...")
        
        try:
            # Parse log file
            df = parse_log_file(log_file_path)
            
            # Separate single-value channels
            time_series_df, single_value_df = separate_single_value_channels(df)
            
            # Save time series CSV
            csv_filename = f"{battery_sn}_{test_type}.csv"
            csv_path = os.path.join(output_csv_dir, csv_filename)
            time_series_df.to_csv(csv_path)
            
            # Save single value CSV if there are any
            single_csv_path = None
            if len(single_value_df.columns) > 0:
                single_csv_filename = f"{battery_sn}_{test_type}_single_values.csv"
                single_csv_path = os.path.join(output_csv_dir, single_csv_filename)
                single_value_df.to_csv(single_csv_path)
            
            # Store file info
            processed_files[f"{battery_sn}_{test_type}"] = {
                'battery_sn': battery_sn,
                'test_type': test_type,
                'log_file_path': log_file_path,
                'csv_path': csv_path,
                'single_csv_path': single_csv_path,
                'start_time': df.index.min().isoformat(),
                'stop_time': df.index.max().isoformat()
            }
            
            # Clean up memory after each file
            del df, time_series_df, single_value_df
            gc.collect()
            
        except Exception as e:
            safe_print(f"  ❌ Error processing {battery_sn} - {test_type}: {str(e)}")
    
    # Mark step as completed
    mark_step_completed(step_name, progress, processed_files)
    safe_print(f"✅ {step_name} completed! Processed {len(processed_files)} files.")
    
    return processed_files

def step2_create_datasets_and_runs(processed_files: dict, progress: dict):
    """Step 2: Create datasets, upload to Nominal, and create runs."""
    step_name = "step2_create_datasets_and_runs"
    
    if is_step_completed(step_name, progress):
        safe_print(f"✅ {step_name} already completed, skipping...")
        return progress[step_name].get('data', {})
    
    safe_print(f"🔄 Starting {step_name}...")
    
    # Initialize Nominal client
    try:
        if PROFILE_NAME != "your-profile-name":
            client = NominalClient.from_profile(profile=PROFILE_NAME)
        else:
            client = get_default_client()
        safe_print(f"Connected to Nominal with profile: {PROFILE_NAME}")
    except Exception as e:
        safe_print(f"❌ Error connecting to Nominal: {str(e)}")
        return {}
    
    # Process each file using the original process_single_log function sequentially
    run_info = {}
    total_files = len(processed_files)
    for i, (file_key, file_info) in enumerate(processed_files.items(), 1):
        battery_sn = file_info['battery_sn']
        test_type = file_info['test_type']
        log_file_path = file_info['log_file_path']
        output_csv_dir = os.path.dirname(file_info['csv_path'])
        
        safe_print(f"Processing {i}/{total_files}: {battery_sn} - {test_type}...")
        
        try:
            # Use the original process_single_log function
            run_rid = process_single_log(battery_sn, test_type, log_file_path, output_csv_dir, client)
            
            if run_rid:
                run_info[file_key] = {
                    'run_rid': run_rid,
                    'battery_sn': battery_sn,
                    'test_type': test_type
                }
                safe_print(f"  🎉 Completed {battery_sn} - {test_type}!")
            else:
                safe_print(f"  ❌ Failed to create run for {battery_sn} - {test_type}")
            
            # Clean up memory after each file
            gc.collect()
                
        except Exception as e:
            safe_print(f"  ❌ Error processing {battery_sn} - {test_type}: {str(e)}")
    
    # Mark step as completed
    mark_step_completed(step_name, progress, run_info)
    safe_print(f"✅ {step_name} completed! Created {len(run_info)} datasets and runs.")
    
    return run_info

def step3_execute_checklists(run_info: dict, pre_post_checklist_rid: str, during_test_checklist_rid: str, progress: dict):
    """Step 3: Execute checklists on runs."""
    step_name = "step3_execute_checklists"
    
    if is_step_completed(step_name, progress):
        safe_print(f"✅ {step_name} already completed, skipping...")
        return
    
    safe_print(f"🔄 Starting {step_name}...")
    
    if not (pre_post_checklist_rid or during_test_checklist_rid):
        safe_print("⚠️  No checklist RIDs provided, skipping checklist execution")
        mark_step_completed(step_name, progress)
        return
    
    # Initialize Nominal client
    try:
        if PROFILE_NAME != "your-profile-name":
            client = NominalClient.from_profile(profile=PROFILE_NAME)
        else:
            client = get_default_client()
    except Exception as e:
        safe_print(f"❌ Error connecting to Nominal: {str(e)}")
        return
    
    # Group runs by test type
    pre_post_runs = []
    during_test_runs = []
    
    for file_key, info in run_info.items():
        test_type = info['test_type']
        if test_type in ["pre_test", "post_test"]:
            pre_post_runs.append((info['run_rid'], test_type))
        elif test_type == "during_test":
            during_test_runs.append((info['run_rid'], test_type))
    
    # Execute pre/post test checklist
    if pre_post_runs and pre_post_checklist_rid:
        safe_print(f"Executing pre/post test checklist on {len(pre_post_runs)} runs...")
        try:
            checklist = client.get_checklist(rid=pre_post_checklist_rid)
            for run_rid, test_type in pre_post_runs:
                try:
                    run = client.get_run(rid=run_rid)
                    result = checklist.execute(run=run)
                    safe_print(f"✅ Pre/post checklist executed on {test_type} run {run_rid}: {result.rid}")
                except Exception as e:
                    safe_print(f"❌ Error executing pre/post checklist on {test_type} run {run_rid}: {str(e)}")
        except Exception as e:
            safe_print(f"❌ Error getting pre/post checklist: {str(e)}")
    
    # Execute during test checklist
    if during_test_runs and during_test_checklist_rid:
        safe_print(f"Executing during test checklist on {len(during_test_runs)} runs...")
        try:
            checklist = client.get_checklist(rid=during_test_checklist_rid)
            for run_rid, test_type in during_test_runs:
                try:
                    run = client.get_run(rid=run_rid)
                    result = checklist.execute(run=run)
                    safe_print(f"✅ During test checklist executed on {test_type} run {run_rid}: {result.rid}")
                except Exception as e:
                    safe_print(f"❌ Error executing during test checklist on {test_type} run {run_rid}: {str(e)}")
        except Exception as e:
            safe_print(f"❌ Error getting during test checklist: {str(e)}")
    
    # Mark step as completed
    mark_step_completed(step_name, progress)
    safe_print(f"✅ {step_name} completed!")

def main():
    """Main processing function with step-by-step execution."""
    parser = argparse.ArgumentParser(description='Process Muon log files in batch with step-by-step execution')
    parser.add_argument('header_folder', help='Path to header folder containing log subfolders')
    parser.add_argument('output_csv_dir', help='Path to directory for saving intermediate CSVs')
    parser.add_argument('--pre-post-checklist-rid', help='RID of checklist for pre-test and post-test runs')
    parser.add_argument('--during-test-checklist-rid', help='RID of checklist for during-test runs')
    parser.add_argument('--step', choices=['1', '2', '3', 'all'], default='all', 
                       help='Which step to run (1=parse logs, 2=create datasets and runs, 3=execute checklists, all=run all steps)')
    parser.add_argument('--reset', action='store_true', help='Reset progress and start from beginning')
    
    args = parser.parse_args()
    
    header_folder = args.header_folder
    output_csv_dir = args.output_csv_dir
    pre_post_checklist_rid = args.pre_post_checklist_rid or PRE_POST_TEST_CHECKLIST_RID
    during_test_checklist_rid = args.during_test_checklist_rid or DURING_TEST_CHECKLIST_RID
    step = args.step
    reset = args.reset
    
    # Load or reset progress
    if reset and os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        safe_print("🔄 Progress reset, starting from beginning...")
    
    progress = load_progress()
    
    # Show current progress
    safe_print("📊 Current Progress:")
    for step_name in ['step1_parse_logs', 'step2_create_datasets_and_runs', 'step3_execute_checklists']:
        status = "✅ Completed" if is_step_completed(step_name, progress) else "⏳ Pending"
        safe_print(f"  {step_name}: {status}")
    
    safe_print("")
    
    # Execute steps based on selection
    if step == '1' or step == 'all':
        processed_files = step1_parse_logs(header_folder, output_csv_dir, progress)
        if not processed_files:
            safe_print("❌ Step 1 failed, stopping execution")
            return
    else:
        processed_files = progress.get('step1_parse_logs', {}).get('data', {})
        if not processed_files:
            safe_print("❌ Step 1 not completed, cannot proceed")
            return
    
    if step == '2' or step == 'all':
        run_info = step2_create_datasets_and_runs(processed_files, progress)
        if not run_info:
            safe_print("❌ Step 2 failed, stopping execution")
            return
    else:
        run_info = progress.get('step2_create_datasets_and_runs', {}).get('data', {})
        if not run_info:
            safe_print("❌ Step 2 not completed, cannot proceed")
            return
    
    if step == '3' or step == 'all':
        step3_execute_checklists(run_info, pre_post_checklist_rid, during_test_checklist_rid, progress)
    
    # Final summary
    safe_print("\n🎉 Processing Summary:")
    safe_print(f"  📁 Processed files: {len(processed_files)}")
    safe_print(f"  🏃 Created runs: {len(run_info)}")
    
    if step == 'all':
        safe_print("✅ All steps completed successfully!")
    else:
        safe_print(f"✅ Step {step} completed successfully!")

if __name__ == "__main__":
    main()