#!/usr/bin/env python3
"""
Filtered TDMS converter that handles large datasets by filtering out problematic columns
"""

import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path
from tdms_batch_converter import TDMSBatchConverter

class FilteredTDMSConverter(TDMSBatchConverter):
    """TDMS converter with filtering capabilities for large datasets"""
    
    def filter_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter out problematic columns and rows from the DataFrame.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Filtered DataFrame
        """
        print(f"  Filtering DataFrame with {len(df)} rows, {len(df.columns)} columns...")
        
        # Remove columns that are mostly text/strings
        numeric_columns = []
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                numeric_columns.append(col)
            elif df[col].dtype == 'object':
                # Check if column is mostly numeric
                try:
                    pd.to_numeric(df[col], errors='coerce')
                    # If we can convert to numeric, keep it
                    numeric_columns.append(col)
                except:
                    # Skip columns that can't be converted to numeric
                    print(f"    Skipping non-numeric column: {col}")
                    continue
            else:
                numeric_columns.append(col)
        
        # Keep only numeric columns
        df_filtered = df[numeric_columns].copy()
        
        # Remove columns with all NaN values
        df_filtered = df_filtered.dropna(axis=1, how='all')
        
        # Remove rows with all NaN values
        df_filtered = df_filtered.dropna(axis=0, how='all')
        
        # Limit to reasonable number of columns (max 50)
        if len(df_filtered.columns) > 50:
            print(f"    Limiting to first 50 columns (was {len(df_filtered.columns)})")
            df_filtered = df_filtered.iloc[:, :50]
        
        print(f"  Filtered to {len(df_filtered)} rows, {len(df_filtered.columns)} columns")
        return df_filtered
    
    def load_tdms_file(self, file_path: Path):
        """Override to add filtering"""
        df, metadata = super().load_tdms_file(file_path)
        
        if df is not None:
            # Filter the DataFrame
            df_filtered = self.filter_dataframe(df)
            metadata['rows_after_filtering'] = len(df_filtered)
            metadata['columns_after_filtering'] = len(df_filtered.columns)
            return df_filtered, metadata
        
        return df, metadata
    
    def merge_dataframes(self, dataframes, merge_strategy='concat'):
        """Override to add size limiting"""
        if not dataframes:
            return pd.DataFrame()
        
        # Limit total number of rows to prevent memory issues
        max_rows = 100000  # Limit to 100k rows
        total_rows = sum(len(df) for df in dataframes)
        
        if total_rows > max_rows:
            print(f"  Large dataset detected ({total_rows:,} rows). Sampling to {max_rows:,} rows...")
            
            # Sample data from each DataFrame proportionally
            sampled_dfs = []
            for df in dataframes:
                if len(df) > 0:
                    sample_size = min(len(df), max_rows // len(dataframes))
                    if sample_size < len(df):
                        # Sample evenly across the DataFrame
                        step = len(df) // sample_size
                        sampled_df = df.iloc[::step].copy()
                    else:
                        sampled_df = df.copy()
                    sampled_dfs.append(sampled_df)
            
            dataframes = sampled_dfs
        
        return super().merge_dataframes(dataframes, merge_strategy)

def main():
    if len(sys.argv) < 3:
        print("Usage: python convert_tdms_filtered.py <input_folder> <output_file>")
        print("Example: python convert_tdms_filtered.py '/Users/ashenoy/Downloads/Hotfire 1' bzb_hotfire_1.sun")
        return 1
    
    # Get arguments
    input_folder = sys.argv[1]
    output_file = sys.argv[2]
    
    # Check if input folder exists
    if not os.path.exists(input_folder):
        print(f"❌ Input folder does not exist: {input_folder}")
        return 1
    
    print(f"Input folder: {input_folder}")
    print(f"Output file: {output_file}")
    
    # Create filtered converter and process
    converter = FilteredTDMSConverter(input_folder, output_file)
    
    try:
        success = converter.process_files()
        
        if success:
            print("\n🎉 Conversion completed successfully!")
            summary = converter.get_summary()
            print(f"Processed {summary['total_files_processed']} files")
            print(f"Combined into {summary['total_rows']:,} rows")
            print(f"Output file: {summary['output_file']}")
            return 0
        else:
            print("\n❌ Conversion failed")
            return 1
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())

