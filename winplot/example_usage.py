#!/usr/bin/env python3
"""
Example usage of the SunAcc pandas wrapper for converting data to Sun files
"""

import pandas as pd
import numpy as np
from sunacc_pandas_wrapper import dataframe_to_sun_file, SunFileWriter

def example_basic_usage():
    """Basic example of converting a DataFrame to Sun file"""
    print("=== Basic Usage Example ===")
    
    # Create sample data
    data = {
        'timestamp': pd.date_range('2023-01-01', periods=100, freq='1s'),
        'temperature': np.random.normal(25, 5, 100),
        'pressure': np.random.normal(1013, 10, 100),
        'flow_rate': np.random.uniform(0, 100, 100)
    }
    
    df = pd.DataFrame(data)
    
    # Define parameter metadata
    metadata = {
        'timestamp': {'units': 's', 'description': 'Timestamp'},
        'temperature': {'units': '°C', 'description': 'Temperature reading'},
        'pressure': {'units': 'hPa', 'description': 'Pressure reading'},
        'flow_rate': {'units': 'L/min', 'description': 'Flow rate'}
    }
    
    # Convert to Sun file
    success = dataframe_to_sun_file(
        df=df,
        filename='example_output.sun',
        file_format='compressed',
        comment='Example data conversion',
        parameter_metadata=metadata
    )
    
    if success:
        print("✅ Successfully created example_output.sun")
    else:
        print("❌ Failed to create Sun file")

def example_context_manager():
    """Example using context manager"""
    print("\n=== Context Manager Example ===")
    
    # Create sample data
    data = {
        'time': np.arange(0, 50, 0.1),  # 0 to 5 seconds in 0.1s steps
        'sensor1': np.sin(np.arange(0, 50, 0.1)),
        'sensor2': np.cos(np.arange(0, 50, 0.1))
    }
    
    df = pd.DataFrame(data)
    
    # Using context manager
    with SunFileWriter() as writer:
        success = writer.create_sun_file(
            filename='example_context.sun',
            df=df,
            file_format='multitime',
            comment='Context manager example'
        )
    
    if success:
        print("✅ Successfully created example_context.sun")
    else:
        print("❌ Failed to create Sun file")

def example_tdms_conversion():
    """Example of converting TDMS-style data"""
    print("\n=== TDMS Conversion Example ===")
    
    # This would be used with your actual TDMS CSV file
    csv_file = "/path/to/your/tdms_data.csv"
    
    print(f"To convert your TDMS data, use:")
    print(f"python process_tdms_data.py")
    print(f"Or modify the csv_file path in this example")

if __name__ == "__main__":
    print("SunAcc Pandas Wrapper - Usage Examples\n")
    
    # Run examples
    example_basic_usage()
    example_context_manager()
    example_tdms_conversion()
    
    print("\n=== Files Created ===")
    print("Check the current directory for .sun files")

