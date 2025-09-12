#!/usr/bin/env python3
"""
Test version of batch processor that skips Nominal upload to test parsing and CSV generation.
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

# Import the parsing functions from the main script
from batch_muon_log_processor import (
    parse_log_file, 
    separate_single_value_channels, 
    get_battery_sns,
    safe_print
)

def process_single_log_no_upload(battery_sn: str, test_type: str, log_file_path: str, 
                                output_csv_dir: str) -> bool:
    """Process a single log file without uploading to Nominal."""
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
        
        # Save time series CSV
        csv_filename = f"{battery_sn}_{test_type}.csv"
        csv_path = os.path.join(output_csv_dir, csv_filename)
        time_series_df.to_csv(csv_path)
        safe_print(f"Saved time series CSV: {csv_path}")
        
        # Save single value CSV if there are any
        if len(single_value_df.columns) > 0:
            single_csv_filename = f"{battery_sn}_{test_type}_single_values.csv"
            single_csv_path = os.path.join(output_csv_dir, single_csv_filename)
            single_value_df.to_csv(single_csv_path)
            safe_print(f"Saved single values CSV: {single_csv_path}")
        
        safe_print(f"✅ Successfully processed {battery_sn} - {test_type}")
        return True
        
    except Exception as e:
        safe_print(f"❌ Error processing {battery_sn} - {test_type}: {str(e)}")
        return False

def main():
    """Test processing without upload."""
    parser = argparse.ArgumentParser(description='Test Muon log processing without upload')
    parser.add_argument('header_folder', help='Path to header folder containing log subfolders')
    parser.add_argument('output_csv_dir', help='Path to directory for saving intermediate CSVs')
    parser.add_argument('--max-workers', type=int, default=2, help='Maximum number of parallel workers')
    
    args = parser.parse_args()
    
    header_folder = args.header_folder
    output_csv_dir = args.output_csv_dir
    max_workers = args.max_workers
    
    # Create output directory
    os.makedirs(output_csv_dir, exist_ok=True)
    
    # Get battery serial numbers
    battery_sns = get_battery_sns(header_folder)
    safe_print(f"Found {len(battery_sns)} battery serial numbers: {battery_sns}")
    
    # Prepare processing tasks
    tasks = []
    for battery_sn in battery_sns:
        for test_type, folder_name in [
            ("pre_test", "Muon_Charge_Logs_Pre_Temp"),
            ("post_test", "Muon_Charge_Logs_Post_Temp"), 
            ("during_test", "Muon_Temp_Cycle_Logs")
        ]:
            log_file_path = os.path.join(header_folder, folder_name, f"{battery_sn}.log")
            if os.path.exists(log_file_path):
                tasks.append((battery_sn, test_type, log_file_path))
            else:
                safe_print(f"Warning: Log file not found: {log_file_path}")
    
    safe_print(f"Processing {len(tasks)} log files with {max_workers} parallel workers...")
    
    # Process files in parallel
    success_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_task = {
            executor.submit(process_single_log_no_upload, battery_sn, test_type, log_file_path, output_csv_dir): (battery_sn, test_type)
            for battery_sn, test_type, log_file_path in tasks
        }
        
        # Collect results
        for future in concurrent.futures.as_completed(future_to_task):
            battery_sn, test_type = future_to_task[future]
            try:
                success = future.result()
                if success:
                    success_count += 1
            except Exception as e:
                safe_print(f"Task failed for {battery_sn} - {test_type}: {str(e)}")
    
    safe_print(f"✅ Processing complete! Successfully processed {success_count}/{len(tasks)} files.")
    safe_print("📁 Check the output CSV directory for results.")

if __name__ == "__main__":
    main()


