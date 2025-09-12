#!/usr/bin/env python3
"""
Sun File Converter - By Data Rate

Converts TDMS or CSV files to Sun files, grouping by data rate.
Creates separate Sun files for each data rate to avoid alignment issues.
"""

import pandas as pd
import numpy as np
import os
import argparse
from pathlib import Path
from nptdms import TdmsFile
import re

# Import our wrapper
from sunacc_pandas_wrapper import dataframe_to_sun_file

def load_tdms_file(file_path):
    """Load a TDMS file and return a DataFrame."""
    try:
        print(f"Loading {os.path.basename(file_path)}...")
        tdms_file = TdmsFile(file_path)
        
        file_data = {}
        for group in tdms_file.groups():
            for channel in group.channels():
                col_name = f'{group.name}_{channel.name}'
                file_data[col_name] = channel.data
        
        if file_data:
            df = pd.DataFrame(file_data)
            print(f"  ✅ Loaded {len(df)} rows, {len(df.columns)} columns")
            return df
        else:
            print(f"  ❌ No data found in {os.path.basename(file_path)}")
            return None
            
    except Exception as e:
        print(f"  ❌ Error loading {os.path.basename(file_path)}: {e}")
        return None

def load_csv_file(file_path):
    """Load a CSV file and return a DataFrame."""
    try:
        print(f"Loading {os.path.basename(file_path)}...")
        df = pd.read_csv(file_path)
        print(f"  ✅ Loaded {len(df)} rows, {len(df.columns)} columns")
        return df
    except Exception as e:
        print(f"  ❌ Error loading {os.path.basename(file_path)}: {e}")
        return None

def filter_dataframe_rows(df, max_rows):
    """Filter DataFrame to reduce number of rows while keeping all columns."""
    if len(df) <= max_rows:
        print(f"  Kept all {len(df)} rows and {len(df.columns)} columns")
        return df
    
    # Systematic sampling to keep representative data
    step = len(df) // max_rows
    if step <= 1:
        step = 1
    
    sampled_df = df.iloc[::step].copy()
    print(f"  Sampled to {len(sampled_df)} rows (keeping all {len(df.columns)} columns)")
    return sampled_df

def extract_data_rate(column_name):
    """Extract data rate from column name and round to single digit."""
    # Look for patterns like "Data (1000.000000 Hz)_param" or "Data (10.000000 Hz)_param"
    match = re.search(r'\((\d+\.?\d*)\s*Hz\)', column_name)
    if match:
        rate_value = float(match.group(1))
        # Round to single digit and remove decimal if it's a whole number
        rounded_rate = round(rate_value, 1)
        if rounded_rate == int(rounded_rate):
            return f"{int(rounded_rate)}Hz"
        else:
            return f"{rounded_rate}Hz"
    return "unknown"

def main():
    parser = argparse.ArgumentParser(description='Convert TDMS/CSV files to separate Sun files by data rate')
    parser.add_argument('input_folder', help='Path to folder containing TDMS/CSV files')
    parser.add_argument('output_folder', help='Output folder for Sun files')
    parser.add_argument('--max-rows', type=int, default=1000000, help='Maximum number of rows per file (default: 1000000)')
    parser.add_argument('--file-type', choices=['auto', 'tdms', 'csv'], default='auto', 
                       help='File type to process (auto-detect by default)')
    
    args = parser.parse_args()
    
    input_folder = Path(args.input_folder)
    output_folder = Path(args.output_folder)
    
    if not input_folder.exists():
        print(f"❌ Input folder does not exist: {input_folder}")
        return 1
    
    # Create output folder if it doesn't exist
    output_folder.mkdir(parents=True, exist_ok=True)
    
    print("=== Sun File Converter (By Data Rate) ===")
    print(f"Input folder: {input_folder}")
    print(f"Output folder: {output_folder}")
    print(f"Max rows: {args.max_rows}")
    print(f"File type: {args.file_type}")
    
    # Find files to process
    files_to_process = []
    if args.file_type == 'tdms' or args.file_type == 'auto':
        tdms_files = list(input_folder.glob("*.tdms"))
        files_to_process.extend([(f, 'tdms') for f in tdms_files])
    if args.file_type == 'csv' or args.file_type == 'auto':
        csv_files = list(input_folder.glob("*.csv"))
        files_to_process.extend([(f, 'csv') for f in csv_files])
    
    if not files_to_process:
        print(f"❌ No {args.file_type} files found in input folder")
        return 1
    
    print(f"Found {len(files_to_process)} files to process")
    
    # Group files by data rate
    rate_groups = {}
    for file_path, f_type in files_to_process:
        if f_type == 'tdms':
            df = load_tdms_file(file_path)
        elif f_type == 'csv':
            df = load_csv_file(file_path)
        else:
            continue
        
        if df is not None:
            # Extract data rate from column names or time column
            data_rate = "unknown"
            
            # First try to extract from column names (for TDMS files)
            for col in df.columns:
                rate = extract_data_rate(col)
                if rate != "unknown":
                    data_rate = rate
                    break
            
            # If not found, try to infer from time column (for CSV files)
            if data_rate == "unknown" and "time" in df.columns:
                try:
                    time_diff = df["time"].diff().mean()
                    if not pd.isna(time_diff) and time_diff > 0:
                        inferred_rate = 1 / time_diff
                        data_rate = f"{round(inferred_rate)}Hz"
                        print(f"  Inferred data rate from time column: {data_rate}")
                except:
                    pass
            
            if data_rate not in rate_groups:
                rate_groups[data_rate] = []
            
            df_filtered = filter_dataframe_rows(df, args.max_rows)
            rate_groups[data_rate].append((file_path, df_filtered))
            print(f"  ✅ Processed {os.path.basename(file_path)} -> {data_rate}")
    
    if not rate_groups:
        print("❌ No valid data found in any files")
        return 1
    
    print(f"\nFound {len(rate_groups)} data rates: {list(rate_groups.keys())}")
    
    # Create separate Sun files for each data rate
    success_count = 0
    for data_rate, file_data in rate_groups.items():
        print(f"\n=== Processing {data_rate} data ===")
        print(f"Files: {len(file_data)}")
        
        # Combine DataFrames for this rate (they should all have the same length)
        dataframes = [df for _, df in file_data]
        combined_df = pd.concat(dataframes, axis=1)
        print(f"  ✅ Combined into {len(combined_df)} rows, {len(combined_df.columns)} columns")
        
        # Final row filtering
        if len(combined_df) > args.max_rows:
            print(f"  Final row filtering...")
            combined_df = filter_dataframe_rows(combined_df, args.max_rows)
            print(f"  ✅ Final dataset: {len(combined_df)} rows, {len(combined_df.columns)} columns")
        
        # Create output filename using input folder name + data rate
        # Replace spaces with underscores for better file system compatibility
        input_folder_name = input_folder.name.replace(" ", "_")
        output_file = output_folder / f"{input_folder_name}_{data_rate}.sun"
        
        # Convert to Sun file
        print(f"Converting to Sun file: {output_file.name}")
        try:
            dataframe_to_sun_file(combined_df, str(output_file))
            print(f"✅ Successfully created Sun file: {output_file}")
            print(f"   File size: {output_file.stat().st_size / 1024:.1f} KB")
            success_count += 1
        except Exception as e:
            print(f"❌ Error creating Sun file for {data_rate}: {e}")
    
    print(f"\n=== Summary ===")
    print(f"Successfully created {success_count}/{len(rate_groups)} Sun files")
    print(f"Output folder: {output_folder}")
    
    return 0

if __name__ == "__main__":
    exit(main())
