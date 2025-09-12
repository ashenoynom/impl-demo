#!/usr/bin/env python3
"""
Example script showing how to use the TDMS Batch Converter
"""

from tdms_batch_converter import TDMSBatchConverter
import pandas as pd
import numpy as np
from pathlib import Path

def create_sample_data():
    """Create some sample TDMS files for testing"""
    print("Creating sample TDMS files...")
    
    # Create test_data directory
    test_dir = Path("test_data")
    test_dir.mkdir(exist_ok=True)
    
    # Create 3 sample files with different data
    for i in range(3):
        # Generate sample data
        n_points = 1000
        time_data = np.arange(0, n_points * 0.1, 0.1)  # 0.1 second intervals
        
        data = {
            'time': time_data,
            f'FMS_ENG_{i+1:02d}': np.random.normal(50, 10, n_points),
            f'PI_FU_{i+1:02d}': np.random.normal(2.0, 0.1, n_points),
            f'PT_ENG_{i+1:02d}': np.random.normal(15, 2, n_points),
            f'TC_FU_{i+1:02d}': np.random.normal(-200, 20, n_points),
        }
        
        df = pd.DataFrame(data)
        
        # Save as CSV
        filename = test_dir / f"test_data_{i+1:02d}.csv"
        df.to_csv(filename, index=False)
        print(f"  Created {filename}")
    
    print(f"✅ Created {len(list(test_dir.glob('*.csv')))} sample files in test_data/")

def example_batch_conversion():
    """Example of batch converting TDMS files"""
    print("\n=== Batch Conversion Example ===")
    
    # Create sample data if it doesn't exist
    test_dir = Path("test_data")
    if not test_dir.exists() or len(list(test_dir.glob("*.csv"))) == 0:
        create_sample_data()
    
    # Example 1: Simple concatenation
    print("\n1. Simple concatenation (default):")
    converter1 = TDMSBatchConverter("test_data", "batch_output_concat.sun")
    success1 = converter1.process_files(merge_strategy='concat')
    
    if success1:
        summary1 = converter1.get_summary()
        print(f"   ✅ Created {summary1['output_file']} with {summary1['total_rows']:,} rows")
    
    # Example 2: Union merge (all columns from all files)
    print("\n2. Union merge (all columns):")
    converter2 = TDMSBatchConverter("test_data", "batch_output_union.sun")
    success2 = converter2.process_files(merge_strategy='union')
    
    if success2:
        summary2 = converter2.get_summary()
        print(f"   ✅ Created {summary2['output_file']} with {summary2['total_rows']:,} rows")
    
    # Example 3: Intersection merge (only common columns)
    print("\n3. Intersection merge (common columns only):")
    converter3 = TDMSBatchConverter("test_data", "batch_output_intersection.sun")
    success3 = converter3.process_files(merge_strategy='intersection')
    
    if success3:
        summary3 = converter3.get_summary()
        print(f"   ✅ Created {summary3['output_file']} with {summary3['total_rows']:,} rows")
    
    return success1 and success2 and success3

def example_with_real_data():
    """Example with real TDMS data folder"""
    print("\n=== Real Data Example ===")
    
    # This would be used with your actual TDMS data folder
    real_data_folder = "/path/to/your/tdms/files"
    
    print(f"To process real TDMS data:")
    print(f"1. Put your TDMS files in a folder")
    print(f"2. Run: python tdms_batch_converter.py {real_data_folder} output.sun")
    print(f"3. Or use the Python API:")
    print(f"   converter = TDMSBatchConverter('{real_data_folder}', 'output.sun')")
    print(f"   converter.process_files()")

if __name__ == "__main__":
    print("TDMS Batch Converter - Examples\n")
    
    # Run examples
    success = example_batch_conversion()
    example_with_real_data()
    
    if success:
        print("\n🎉 All examples completed successfully!")
        print("\nGenerated files:")
        print("- batch_output_concat.sun (concatenated data)")
        print("- batch_output_union.sun (all columns)")
        print("- batch_output_intersection.sun (common columns only)")
    else:
        print("\n❌ Some examples failed")

