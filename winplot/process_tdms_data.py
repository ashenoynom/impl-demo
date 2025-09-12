#!/usr/bin/env python3
"""
Process TDMS CSV data and convert to Sun file using the SunAcc wrapper
"""

import pandas as pd
import numpy as np
from sunacc_pandas_wrapper import dataframe_to_sun_file, SunFileWriter

def load_and_process_tdms_data(csv_file_path):
    """
    Load and process the TDMS CSV data for Sun file conversion
    
    Args:
        csv_file_path: Path to the TDMS CSV file
        
    Returns:
        tuple: (processed_dataframe, parameter_metadata)
    """
    print(f"Loading data from {csv_file_path}...")
    
    # Load the CSV file
    df = pd.read_csv(csv_file_path)
    
    print(f"Loaded {len(df)} rows and {len(df.columns)} columns")
    print(f"Columns: {list(df.columns)}")
    
    # Check data types
    print(f"\nData types:")
    print(df.dtypes)
    
    # Process the time column
    if 'time' in df.columns:
        print(f"\nTime column range: {df['time'].min()} to {df['time'].max()}")
        # Convert time to datetime if it's in seconds since start
        if df['time'].dtype in ['float64', 'int64']:
            # Assume time is in seconds, create a proper datetime
            start_time = pd.Timestamp('2025-06-17T19:43:02.341409619Z')
            df['timestamp'] = start_time + pd.to_timedelta(df['time'], unit='s')
            print(f"Created timestamp column from time data")
        else:
            df['timestamp'] = pd.to_datetime(df['time'])
    else:
        print("No time column found, creating index-based time")
        df['timestamp'] = pd.date_range('2025-06-17T19:43:02', periods=len(df), freq='1ms')
    
    # Create parameter metadata based on column names
    parameter_metadata = {}
    
    for col in df.columns:
        if col == 'time':
            continue  # Skip the original time column
            
        # Determine parameter type and units based on column name
        if col.startswith('FMS_'):
            parameter_metadata[col] = {
                'units': 'Hz',
                'description': f'Frequency measurement - {col}'
            }
        elif col.startswith('PI_'):
            parameter_metadata[col] = {
                'units': 'bar',
                'description': f'Pressure indicator - {col}'
            }
        elif col.startswith('PT_'):
            parameter_metadata[col] = {
                'units': 'bar',
                'description': f'Pressure transducer - {col}'
            }
        elif col.startswith('TC_'):
            parameter_metadata[col] = {
                'units': '°C',
                'description': f'Temperature controller - {col}'
            }
        elif col == 'timestamp':
            parameter_metadata[col] = {
                'units': 's',
                'description': 'Timestamp'
            }
        else:
            parameter_metadata[col] = {
                'units': '',
                'description': f'Parameter - {col}'
            }
    
    return df, parameter_metadata

def create_sun_file_from_tdms(csv_file_path, output_sun_file, file_format='compressed'):
    """
    Convert TDMS CSV data to Sun file
    
    Args:
        csv_file_path: Path to input CSV file
        output_sun_file: Path for output Sun file
        file_format: Sun file format ('compressed', 'multitime', 'uncompressed')
    """
    try:
        # Load and process the data
        df, metadata = load_and_process_tdms_data(csv_file_path)
        
        print(f"\nCreating Sun file: {output_sun_file}")
        print(f"Format: {file_format}")
        print(f"Data shape: {df.shape}")
        
        # Create the Sun file
        success = dataframe_to_sun_file(
            df=df,
            filename=output_sun_file,
            file_format=file_format,
            comment=f'TDMS data converted from {csv_file_path}',
            parameter_metadata=metadata
        )
        
        if success:
            print(f"✅ Successfully created {output_sun_file}")
            
            # Show file info
            import os
            file_size = os.path.getsize(output_sun_file)
            print(f"File size: {file_size:,} bytes")
            
            return True
        else:
            print(f"❌ Failed to create {output_sun_file}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def analyze_data_quality(df):
    """Analyze the quality of the loaded data"""
    print("\n=== Data Quality Analysis ===")
    
    # Check for missing values
    missing_data = df.isnull().sum()
    if missing_data.any():
        print("Missing values per column:")
        print(missing_data[missing_data > 0])
    else:
        print("✅ No missing values found")
    
    # Check data ranges
    print("\nData ranges:")
    for col in df.select_dtypes(include=[np.number]).columns:
        if col != 'time':  # Skip time column
            print(f"{col}: {df[col].min():.3f} to {df[col].max():.3f}")
    
    # Check for constant columns
    constant_cols = []
    for col in df.columns:
        if df[col].nunique() <= 1:
            constant_cols.append(col)
    
    if constant_cols:
        print(f"\n⚠️  Constant columns (no variation): {constant_cols}")
    else:
        print("\n✅ No constant columns found")

if __name__ == "__main__":
    # Input file path
    csv_file = "/Users/ashenoy/Downloads/2025-06-17T19_43_02.341409619Z_TDMSData.csv"
    
    # Output file paths
    output_compressed = "tdms_data_compressed.sun"
    output_multitime = "tdms_data_multitime.sun"
    
    print("=== TDMS Data to Sun File Converter ===\n")
    
    # First, let's analyze the data
    try:
        df, metadata = load_and_process_tdms_data(csv_file)
        analyze_data_quality(df)
        
        print(f"\n=== Converting to Sun Files ===")
        
        # Create compressed format
        print("\n1. Creating compressed format...")
        success1 = create_sun_file_from_tdms(csv_file, output_compressed, 'compressed')
        
        # Create multitime format
        print("\n2. Creating multitime format...")
        success2 = create_sun_file_from_tdms(csv_file, output_multitime, 'multitime')
        
        print(f"\n=== Results ===")
        print(f"Compressed format: {'✅ SUCCESS' if success1 else '❌ FAILED'}")
        print(f"Multitime format: {'✅ SUCCESS' if success2 else '❌ FAILED'}")
        
        if success1 or success2:
            print(f"\n🎉 Sun files created successfully!")
            print(f"You can now use these .sun files with SunAcc-compatible applications.")
        else:
            print(f"\n❌ Failed to create Sun files")
            
    except Exception as e:
        print(f"❌ Error processing data: {e}")
