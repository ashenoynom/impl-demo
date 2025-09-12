#!/usr/bin/env python3
"""
TDMS Batch Converter - Row Filtering Only Version
Processes multiple .tdms files from a folder and converts them to a single .sun file.
This version only reduces rows while keeping all unique columns.
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from nptdms import TdmsFile
import warnings

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sunacc_pandas_wrapper import dataframe_to_sun_file

def load_tdms_file(file_path):
    """Load a TDMS file and return a DataFrame."""
    try:
        print(f"Loading {os.path.basename(file_path)}...")
        
        # Try to load as binary TDMS file
        with TdmsFile.open(file_path) as tdms_file:
            data = {}
            
            # Iterate through all groups and channels
            for group in tdms_file.groups():
                group_name = group.name
                for channel in group.channels():
                    channel_name = channel.name
                    # Create a unique column name
                    col_name = f"{group_name}_{channel_name}" if group_name != 'root' else channel_name
                    
                    # Get the data as numpy array
                    channel_data = channel[:]
                    
                    # Convert to pandas Series
                    data[col_name] = pd.Series(channel_data)
            
            if not data:
                print(f"  ⚠️  No data found in {os.path.basename(file_path)}")
                return None
                
            df = pd.DataFrame(data)
            print(f"  ✅ Loaded {len(df)} rows, {len(df.columns)} columns")
            return df
            
    except Exception as e:
        print(f"  ❌ Error loading {os.path.basename(file_path)}: {e}")
        return None

def filter_dataframe_rows(df, max_rows=50000):
    """
    Filter DataFrame to reduce rows while keeping all columns.
    """
    print(f"  Row filtering DataFrame with {len(df)} rows, {len(df.columns)} columns...")
    
    # Keep all columns - no column filtering
    df_filtered = df.copy()
    
    # Only sample rows if too many
    if len(df_filtered) > max_rows:
        # Use systematic sampling to get representative data
        step = len(df_filtered) // max_rows
        df_filtered = df_filtered.iloc[::step].head(max_rows)
        print(f"  Sampled to {len(df_filtered)} rows (keeping all {len(df_filtered.columns)} columns)")
    else:
        print(f"  Kept all {len(df_filtered)} rows and {len(df_filtered.columns)} columns")
    
    return df_filtered

def main():
    parser = argparse.ArgumentParser(description='Convert multiple TDMS files to a single Sun file (row filtering only)')
    parser.add_argument('input_folder', help='Path to folder containing TDMS files')
    parser.add_argument('output_file', help='Output Sun file path')
    parser.add_argument('--max-rows', type=int, default=50000, help='Maximum number of rows (default: 50000)')
    
    args = parser.parse_args()
    
    input_folder = Path(args.input_folder)
    output_file = Path(args.output_file)
    
    if not input_folder.exists():
        print(f"❌ Input folder does not exist: {input_folder}")
        return 1
    
    print("=== TDMS Batch Converter (Row Filtering Only) ===")
    print(f"Input folder: {input_folder}")
    print(f"Output file: {output_file}")
    print(f"Max rows: {args.max_rows}")
    
    # Find all TDMS files
    tdms_files = list(input_folder.glob("*.tdms"))
    if not tdms_files:
        print("❌ No TDMS files found in input folder")
        return 1
    
    print(f"Found {len(tdms_files)} TDMS files to process")
    
    # Load and process each file
    dataframes = []
    for tdms_file in tdms_files:
        df = load_tdms_file(tdms_file)
        if df is not None:
            # Apply row filtering
            df_filtered = filter_dataframe_rows(df, args.max_rows)
            if len(df_filtered) > 0:
                dataframes.append(df_filtered)
                print(f"  ✅ Processed {tdms_file.name}")
            else:
                print(f"  ⚠️  Skipped {tdms_file.name} (no data after filtering)")
    
    if not dataframes:
        print("❌ No valid data found in any TDMS files")
        return 1
    
    print(f"\nSuccessfully processed {len(dataframes)}/{len(tdms_files)} files")
    
    # Merge all DataFrames
    print(f"Merging {len(dataframes)} DataFrames...")
    combined_df = pd.concat(dataframes, ignore_index=True, sort=False)
    print(f"  ✅ Combined into {len(combined_df)} rows, {len(combined_df.columns)} columns")
    
    # Final row filtering
    if len(combined_df) > args.max_rows:
        print(f"  Final row filtering...")
        combined_df = filter_dataframe_rows(combined_df, args.max_rows)
        print(f"  ✅ Final dataset: {len(combined_df)} rows, {len(combined_df.columns)} columns")
    
    # Convert to Sun file
    print(f"\nConverting to Sun file...")
    try:
        dataframe_to_sun_file(combined_df, str(output_file))
        print(f"✅ Successfully created Sun file: {output_file}")
        print(f"   File size: {output_file.stat().st_size / 1024:.1f} KB")
        return 0
    except Exception as e:
        print(f"❌ Error creating Sun file: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
