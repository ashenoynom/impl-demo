#!/usr/bin/env python3
"""
TDMS Batch Converter

A script that ingests multiple TDMS files from a folder, combines them into a single table,
and outputs a Sun file. Supports various TDMS file formats and data merging strategies.

Author: Generated for SunAcc pandas wrapper
"""

import pandas as pd
import numpy as np
import os
import glob
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import warnings
from datetime import datetime
import argparse

# Import our SunAcc wrapper
from sunacc_pandas_wrapper import dataframe_to_sun_file, SunFileWriter

class TDMSBatchConverter:
    """
    A class for batch converting multiple TDMS files to a single Sun file.
    """
    
    def __init__(self, input_folder: str, output_file: str):
        """
        Initialize the TDMS batch converter.
        
        Args:
            input_folder: Path to folder containing TDMS files
            output_file: Path for output Sun file
        """
        self.input_folder = Path(input_folder)
        self.output_file = output_file
        self.combined_df = None
        self.file_info = []
        
    def find_tdms_files(self, extensions: List[str] = None) -> List[Path]:
        """
        Find all TDMS files in the input folder.
        
        Args:
            extensions: List of file extensions to look for
            
        Returns:
            List of Path objects for found files
        """
        if extensions is None:
            extensions = ['.csv', '.tdms', '.xlsx', '.xls', '.parquet']
        
        files = []
        for ext in extensions:
            pattern = f"*{ext}"
            files.extend(self.input_folder.glob(pattern))
        
        # Sort files for consistent ordering
        files.sort()
        return files
    
    def load_tdms_file(self, file_path: Path) -> Tuple[pd.DataFrame, Dict]:
        """
        Load a single TDMS file and extract metadata.
        
        Args:
            file_path: Path to the TDMS file
            
        Returns:
            Tuple of (dataframe, metadata_dict)
        """
        print(f"Loading {file_path.name}...")
        
        try:
            # Determine file type and load accordingly
            if file_path.suffix.lower() == '.csv':
                df = pd.read_csv(file_path)
            elif file_path.suffix.lower() in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            elif file_path.suffix.lower() == '.parquet':
                df = pd.read_parquet(file_path)
            elif file_path.suffix.lower() == '.tdms':
                # Handle TDMS files using nptdms
                df = self.load_tdms_binary(file_path)
            else:
                # Try CSV as fallback
                df = pd.read_csv(file_path)
            
            # Extract metadata
            metadata = {
                'source_file': file_path.name,
                'file_size': file_path.stat().st_size,
                'rows': len(df),
                'columns': len(df.columns),
                'column_names': list(df.columns),
                'load_time': datetime.now().isoformat()
            }
            
            print(f"  ✅ Loaded {len(df)} rows, {len(df.columns)} columns")
            return df, metadata
            
        except Exception as e:
            print(f"  ❌ Error loading {file_path.name}: {e}")
            return None, {'error': str(e)}
    
    def load_tdms_binary(self, file_path: Path) -> pd.DataFrame:
        """
        Load a binary TDMS file using nptdms.
        
        Args:
            file_path: Path to the TDMS file
            
        Returns:
            DataFrame with TDMS data
        """
        try:
            from nptdms import TdmsFile
            
            with TdmsFile.open(file_path) as tdms_file:
                # Get all groups and channels
                all_data = {}
                
                # Iterate through all groups and channels
                for group in tdms_file.groups():
                    for channel in group.channels():
                        # Create a unique column name
                        col_name = f"{group.name}_{channel.name}" if group.name != 'root' else channel.name
                        
                        # Get the data
                        data = channel[:]
                        
                        # Convert to pandas Series
                        if hasattr(data, 'tolist'):
                            all_data[col_name] = data.tolist()
                        else:
                            all_data[col_name] = list(data)
                
                # Create DataFrame
                if all_data:
                    # Find the maximum length to pad shorter arrays
                    max_length = max(len(data) for data in all_data.values())
                    
                    # Pad shorter arrays with NaN
                    for col_name, data in all_data.items():
                        if len(data) < max_length:
                            all_data[col_name] = data + [np.nan] * (max_length - len(data))
                    
                    df = pd.DataFrame(all_data)
                else:
                    # No data found, create empty DataFrame
                    df = pd.DataFrame()
                
                return df
                
        except ImportError:
            print(f"  ⚠️  nptdms not available, trying to read as text file...")
            # Fallback: try to read as text with different encodings
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    return df
                except:
                    continue
            raise Exception("Could not read TDMS file with any encoding")
        except Exception as e:
            print(f"  ⚠️  Error reading TDMS file: {e}")
            # Try to read as text file as fallback
            try:
                df = pd.read_csv(file_path, encoding='latin-1')
                return df
            except:
                raise e
    
    def detect_time_column(self, df: pd.DataFrame) -> Optional[str]:
        """
        Detect the time column in a DataFrame.
        
        Args:
            df: DataFrame to analyze
            
        Returns:
            Name of the time column, or None if not found
        """
        # Common time column names
        time_names = ['time', 'timestamp', 'Time', 'Timestamp', 'TIME', 'TIMESTAMP']
        
        # Check for exact matches first
        for col in time_names:
            if col in df.columns:
                return col
        
        # Check for columns that look like time data
        for col in df.columns:
            if df[col].dtype in ['datetime64[ns]', 'datetime64']:
                return col
            
            # Check if column contains numeric time data
            if pd.api.types.is_numeric_dtype(df[col]):
                # If it's numeric and starts from 0 or small values, might be time
                if df[col].min() >= 0 and df[col].max() > 100:
                    return col
        
        return None
    
    def standardize_time_column(self, df: pd.DataFrame, time_col: str, file_index: int) -> pd.DataFrame:
        """
        Standardize the time column across different files.
        
        Args:
            df: DataFrame to standardize
            time_col: Name of the time column
            file_index: Index of the file (for offsetting time)
            
        Returns:
            DataFrame with standardized time column
        """
        df = df.copy()
        
        if time_col and time_col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[time_col]):
                # Already datetime, use as is
                df['timestamp'] = df[time_col]
            else:
                # Convert numeric time to datetime
                # Add file index offset to prevent time overlap
                time_offset = file_index * 10000  # 10k seconds per file
                df['timestamp'] = pd.to_datetime('2023-01-01') + pd.to_timedelta(df[time_col] + time_offset, unit='s')
        else:
            # Create synthetic time based on row index
            time_offset = file_index * 10000
            df['timestamp'] = pd.to_datetime('2023-01-01') + pd.to_timedelta(df.index + time_offset, unit='s')
        
        return df
    
    def merge_dataframes(self, dataframes: List[pd.DataFrame], merge_strategy: str = 'concat') -> pd.DataFrame:
        """
        Merge multiple DataFrames into a single one.
        
        Args:
            dataframes: List of DataFrames to merge
            merge_strategy: Strategy for merging ('concat', 'union', 'intersection')
            
        Returns:
            Combined DataFrame
        """
        if not dataframes:
            return pd.DataFrame()
        
        if len(dataframes) == 1:
            return dataframes[0]
        
        print(f"Merging {len(dataframes)} DataFrames using '{merge_strategy}' strategy...")
        
        if merge_strategy == 'concat':
            # Simple concatenation
            combined = pd.concat(dataframes, ignore_index=True)
            
        elif merge_strategy == 'union':
            # Union of all columns, fill missing with NaN
            all_columns = set()
            for df in dataframes:
                all_columns.update(df.columns)
            
            # Reindex all DataFrames to have the same columns
            standardized_dfs = []
            for df in dataframes:
                df_std = df.reindex(columns=sorted(all_columns))
                standardized_dfs.append(df_std)
            
            combined = pd.concat(standardized_dfs, ignore_index=True)
            
        elif merge_strategy == 'intersection':
            # Only keep columns that exist in all DataFrames
            common_columns = set(dataframes[0].columns)
            for df in dataframes[1:]:
                common_columns = common_columns.intersection(set(df.columns))
            
            if not common_columns:
                raise ValueError("No common columns found across all DataFrames")
            
            # Keep only common columns
            standardized_dfs = [df[sorted(common_columns)] for df in dataframes]
            combined = pd.concat(standardized_dfs, ignore_index=True)
            
        else:
            raise ValueError(f"Unknown merge strategy: {merge_strategy}")
        
        print(f"  ✅ Combined into {len(combined)} rows, {len(combined.columns)} columns")
        return combined
    
    def create_parameter_metadata(self, df: pd.DataFrame) -> Dict[str, Dict[str, str]]:
        """
        Create parameter metadata for the combined DataFrame.
        
        Args:
            df: Combined DataFrame
            
        Returns:
            Dictionary mapping column names to metadata
        """
        metadata = {}
        
        for col in df.columns:
            if col == 'timestamp':
                metadata[col] = {
                    'units': 's',
                    'description': 'Timestamp'
                }
            elif col.startswith('FMS_'):
                metadata[col] = {
                    'units': 'Hz',
                    'description': f'Frequency measurement - {col}'
                }
            elif col.startswith('PI_'):
                metadata[col] = {
                    'units': 'bar',
                    'description': f'Pressure indicator - {col}'
                }
            elif col.startswith('PT_'):
                metadata[col] = {
                    'units': 'bar',
                    'description': f'Pressure transducer - {col}'
                }
            elif col.startswith('TC_'):
                metadata[col] = {
                    'units': '°C',
                    'description': f'Temperature controller - {col}'
                }
            elif col.startswith('time'):
                metadata[col] = {
                    'units': 's',
                    'description': f'Time parameter - {col}'
                }
            else:
                metadata[col] = {
                    'units': '',
                    'description': f'Parameter - {col}'
                }
        
        return metadata
    
    def process_files(self, 
                     merge_strategy: str = 'concat',
                     file_extensions: List[str] = None,
                     max_files: Optional[int] = None) -> bool:
        """
        Process all TDMS files in the input folder.
        
        Args:
            merge_strategy: Strategy for merging DataFrames
            file_extensions: List of file extensions to process
            max_files: Maximum number of files to process (None for all)
            
        Returns:
            True if successful, False otherwise
        """
        print(f"=== TDMS Batch Converter ===")
        print(f"Input folder: {self.input_folder}")
        print(f"Output file: {self.output_file}")
        print(f"Merge strategy: {merge_strategy}")
        
        # Find files
        files = self.find_tdms_files(file_extensions)
        
        if not files:
            print("❌ No TDMS files found in the input folder")
            return False
        
        if max_files:
            files = files[:max_files]
        
        print(f"Found {len(files)} files to process")
        
        # Load and process each file
        dataframes = []
        successful_files = 0
        
        for i, file_path in enumerate(files):
            df, metadata = self.load_tdms_file(file_path)
            
            if df is not None:
                # Detect and standardize time column
                time_col = self.detect_time_column(df)
                df_std = self.standardize_time_column(df, time_col, i)
                
                # Add file identifier
                df_std['source_file'] = file_path.stem
                
                dataframes.append(df_std)
                self.file_info.append(metadata)
                successful_files += 1
                
                print(f"  ✅ Processed {file_path.name}")
            else:
                print(f"  ❌ Skipped {file_path.name}")
        
        if not dataframes:
            print("❌ No files were successfully loaded")
            return False
        
        print(f"\nSuccessfully processed {successful_files}/{len(files)} files")
        
        # Merge DataFrames
        try:
            self.combined_df = self.merge_dataframes(dataframes, merge_strategy)
        except Exception as e:
            print(f"❌ Error merging DataFrames: {e}")
            return False
        
        # Create parameter metadata
        metadata = self.create_parameter_metadata(self.combined_df)
        
        # Convert to Sun file
        print(f"\nConverting to Sun file...")
        try:
            success = dataframe_to_sun_file(
                df=self.combined_df,
                filename=self.output_file,
                file_format='compressed',
                comment=f'Batch converted from {len(dataframes)} TDMS files',
                parameter_metadata=metadata
            )
            
            if success:
                print(f"✅ Successfully created {self.output_file}")
                
                # Show file info
                file_size = os.path.getsize(self.output_file)
                print(f"File size: {file_size:,} bytes")
                print(f"Total rows: {len(self.combined_df):,}")
                print(f"Total columns: {len(self.combined_df.columns)}")
                
                return True
            else:
                print(f"❌ Failed to create Sun file")
                return False
                
        except Exception as e:
            print(f"❌ Error creating Sun file: {e}")
            return False
    
    def get_summary(self) -> Dict:
        """
        Get a summary of the processing results.
        
        Returns:
            Dictionary with processing summary
        """
        if self.combined_df is None:
            return {'error': 'No data processed'}
        
        return {
            'total_files_processed': len(self.file_info),
            'total_rows': len(self.combined_df),
            'total_columns': len(self.combined_df.columns),
            'file_info': self.file_info,
            'output_file': self.output_file,
            'output_file_size': os.path.getsize(self.output_file) if os.path.exists(self.output_file) else 0
        }


def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(description='Convert multiple TDMS files to a single Sun file')
    parser.add_argument('input_folder', help='Path to folder containing TDMS files')
    parser.add_argument('output_file', help='Path for output Sun file')
    parser.add_argument('--merge-strategy', choices=['concat', 'union', 'intersection'], 
                       default='concat', help='Strategy for merging DataFrames')
    parser.add_argument('--extensions', nargs='+', default=['.csv', '.tdms', '.xlsx'],
                       help='File extensions to process')
    parser.add_argument('--max-files', type=int, help='Maximum number of files to process')
    
    # Handle paths with spaces by using nargs='*' and joining
    import sys
    if len(sys.argv) > 2:
        # Check if we have a path with spaces
        input_folder = sys.argv[1]
        output_file = sys.argv[-1]  # Last argument is output file
        
        # If there are more than 2 arguments, the middle ones might be part of the path
        if len(sys.argv) > 3:
            # Reconstruct the input folder path
            input_folder = ' '.join(sys.argv[1:-1])
        
        # Create a mock args object
        class Args:
            def __init__(self):
                self.input_folder = input_folder
                self.output_file = output_file
                self.merge_strategy = 'concat'
                self.extensions = ['.csv', '.tdms', '.xlsx']
                self.max_files = None
        
        args = Args()
    else:
        args = parser.parse_args()
    
    # Create converter
    converter = TDMSBatchConverter(args.input_folder, args.output_file)
    
    # Process files
    success = converter.process_files(
        merge_strategy=args.merge_strategy,
        file_extensions=args.extensions,
        max_files=args.max_files
    )
    
    if success:
        print("\n🎉 Batch conversion completed successfully!")
        summary = converter.get_summary()
        print(f"Processed {summary['total_files_processed']} files")
        print(f"Combined into {summary['total_rows']:,} rows")
        print(f"Output file: {summary['output_file']}")
    else:
        print("\n❌ Batch conversion failed")
        return 1
    
    return 0


if __name__ == "__main__":
    # Example usage if run directly
    if len(os.sys.argv) == 1:
        print("TDMS Batch Converter - Example Usage")
        print("\nCommand line usage:")
        print("python tdms_batch_converter.py <input_folder> <output_file>")
        print("\nExample:")
        print("python tdms_batch_converter.py ./test_data/ combined_output.sun")
        print("\nOptions:")
        print("  --merge-strategy {concat,union,intersection}  How to merge DataFrames")
        print("  --extensions .csv .tdms .xlsx                 File extensions to process")
        print("  --max-files 10                                Maximum files to process")
        
        # Interactive example
        print("\n=== Interactive Example ===")
        
        # Check if test_data folder exists
        test_folder = Path("test_data")
        if test_folder.exists():
            print(f"Found test_data folder with {len(list(test_folder.glob('*')))} files")
            
            converter = TDMSBatchConverter("test_data", "batch_output.sun")
            success = converter.process_files()
            
            if success:
                print("✅ Interactive example completed!")
            else:
                print("❌ Interactive example failed")
        else:
            print("No test_data folder found. Create one with some TDMS files to test.")
    else:
        exit(main())
