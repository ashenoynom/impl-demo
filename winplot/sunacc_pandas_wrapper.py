"""
SunAcc Pandas Wrapper - Fixed Version

A wrapper class that allows you to create Sun files from pandas DataFrames.
This module provides an easy-to-use interface for converting pandas DataFrames
to Sun format files using the SunAcc library.

Author: Generated wrapper for SunAcc package
"""

import pandas as pd
import numpy as np
import os
from typing import Dict, List, Optional, Union, Any
import warnings

# Import SunAcc module
try:
    import SunAcc
except ImportError:
    raise ImportError("SunAcc module not found. Please ensure it's installed in your environment.")

class SunFileWriter:
    """
    A wrapper class for creating Sun files from pandas DataFrames.
    
    This class provides methods to:
    - Convert pandas DataFrames to Sun format files
    - Handle data type conversions automatically
    - Support metadata (units, descriptions) for parameters
    - Create both compressed and uncompressed Sun files
    """
    
    def __init__(self):
        """Initialize the SunFileWriter."""
        self.sunwrt = None
        self.is_file_open = False
        
        # Data type mapping from pandas/numpy to SunAcc types
        self.data_type_mapping = {
            'int8': SunAcc.DTS_BYTE,
            'int16': SunAcc.DTS_SHORTINT,
            'int32': SunAcc.DTS_LONGINT,
            'int64': SunAcc.DTS_LONGLONG,
            'uint8': SunAcc.DTS_BYTE,
            'uint16': SunAcc.DTS_USHORTINT,
            'uint32': SunAcc.DTS_ULONGINT,
            'uint64': SunAcc.DTS_ULONGLONG,
            'float32': SunAcc.DTS_FLOAT,
            'float64': SunAcc.DTS_DOUBLE,
            'bool': SunAcc.DTS_BYTE,
            'object': SunAcc.DTS_FLOAT,  # Default for string/object types
        }
        
        # File format constants
        self.SUN_COMPRESSED = SunAcc.SUN_COMPRESSED
        self.SUN_MULTITIME = SunAcc.SUN_MULTITIME
        self.SUN_UNCOMPRESSED = SunAcc.SUN_UNCOMPRESSED
        
        # Write mode constants
        self.WRITE_MODE_OVERWRITE = 0
        self.WRITE_MODE_UPDATE = 1
    
    def _infer_data_type(self, series: pd.Series) -> str:
        """
        Infer the appropriate SunAcc data type for a pandas Series.
        
        Args:
            series: pandas Series to analyze
            
        Returns:
            str: SunAcc data type identifier
        """
        # Handle missing values first
        if series.isna().any():
            series_clean = series.dropna()
            if len(series_clean) == 0:
                return SunAcc.DTS_FLOAT  # Default for all-NaN series
        else:
            series_clean = series
        
        # Additional safety check for empty series
        if len(series_clean) == 0:
            return SunAcc.DTS_FLOAT
        
        # Handle datetime types first (before numeric check)
        if pd.api.types.is_datetime64_any_dtype(series_clean):
            return SunAcc.DTS_TIMETAG
        
        # Handle boolean types
        if pd.api.types.is_bool_dtype(series_clean):
            return SunAcc.DTS_BYTE
        
        # Handle numeric types
        if pd.api.types.is_numeric_dtype(series_clean):
            if pd.api.types.is_integer_dtype(series_clean):
                min_val = series_clean.min()
                max_val = series_clean.max()
                
                # Handle NaN values in min/max
                if pd.isna(min_val) or pd.isna(max_val):
                    return SunAcc.DTS_FLOAT  # Default for series with NaN min/max
                
                if min_val >= 0:  # Unsigned integer
                    if max_val <= 255:
                        return SunAcc.DTS_BYTE
                    elif max_val <= 65535:
                        return SunAcc.DTS_USHORTINT
                    elif max_val <= 4294967295:
                        return SunAcc.DTS_ULONGINT
                    else:
                        return SunAcc.DTS_ULONGLONG
                else:  # Signed integer
                    if min_val >= -128 and max_val <= 127:
                        return SunAcc.DTS_BYTE
                    elif min_val >= -32768 and max_val <= 32767:
                        return SunAcc.DTS_SHORTINT
                    elif min_val >= -2147483648 and max_val <= 2147483647:
                        return SunAcc.DTS_LONGINT
                    else:
                        return SunAcc.DTS_LONGLONG
            else:  # Float
                if series_clean.dtype == 'float32':
                    return SunAcc.DTS_FLOAT
                else:
                    return SunAcc.DTS_DOUBLE
        
        # Handle string/object types - try to convert to numeric
        if series_clean.dtype == 'object':
            # Check if it looks like datetime
            if any(keyword in str(series_clean.iloc[0]).lower() for keyword in ['time', 'date', 'timestamp']):
                return SunAcc.DTS_TIMETAG
            else:
                # Default to float for string data (will be converted to numeric)
                return SunAcc.DTS_FLOAT
        
        # Default to float for other types
        return SunAcc.DTS_FLOAT
    
    def _convert_series_to_array(self, series: pd.Series, data_type: str) -> Union[np.ndarray, List]:
        """
        Convert a pandas Series to a numpy array with the appropriate data type.
        
        Args:
            series: pandas Series to convert
            data_type: SunAcc data type identifier
            
        Returns:
            Union[np.ndarray, List]: Converted array or list of TimeTag objects
        """
        # Handle missing values and non-numeric data
        if series.isna().any():
            warnings.warn(f"Series contains NaN values. Filling with 0.")
            series = series.fillna(0)
        
        # Handle string/non-numeric data
        if not pd.api.types.is_numeric_dtype(series):
            if data_type == SunAcc.DTS_TIMETAG:
                # For TimeTag, try to convert strings to timestamps
                try:
                    series = pd.to_datetime(series, errors='coerce')
                except:
                    # If conversion fails, create dummy timestamps
                    series = pd.Series([pd.Timestamp('2023-01-01')] * len(series))
            else:
                # For other types, try to convert to numeric
                try:
                    series = pd.to_numeric(series, errors='coerce')
                    # Fill any remaining NaN values with 0
                    series = series.fillna(0)
                except:
                    # If all else fails, create a numeric series of zeros
                    series = pd.Series([0.0] * len(series))
        
        # Convert to numpy array
        if data_type == SunAcc.DTS_BYTE:
            return series.astype(np.uint8).values
        elif data_type == SunAcc.DTS_SHORTINT:
            return series.astype(np.int16).values
        elif data_type == SunAcc.DTS_USHORTINT:
            return series.astype(np.uint16).values
        elif data_type == SunAcc.DTS_LONGINT:
            return series.astype(np.int32).values
        elif data_type == SunAcc.DTS_ULONGINT:
            return series.astype(np.uint32).values
        elif data_type == SunAcc.DTS_LONGLONG:
            return series.astype(np.int64).values
        elif data_type == SunAcc.DTS_ULONGLONG:
            return series.astype(np.uint64).values
        elif data_type == SunAcc.DTS_FLOAT:
            return series.astype(np.float32).values
        elif data_type == SunAcc.DTS_DOUBLE:
            return series.astype(np.float64).values
        elif data_type == SunAcc.DTS_TIMETAG:
            # Convert datetime to TimeTag objects
            if pd.api.types.is_datetime64_any_dtype(series):
                timetags = []
                for dt in series:
                    # Convert pandas datetime to TimeTag
                    # TimeTag requires JulianDay, MilliSeconds, MicroSeconds
                    if pd.isna(dt):
                        # Create a default TimeTag for NaN values
                        timetag = SunAcc.TimeTag(None, jday=0, msec=0, usec=0)
                    else:
                        # Convert to timestamp and extract components
                        timestamp = dt.timestamp()
                        julian_day = int(timestamp // 86400) + 2440588  # Convert to Julian day
                        seconds_in_day = timestamp % 86400
                        milliseconds = int(seconds_in_day * 1000)
                        microseconds = int((seconds_in_day * 1000) % 1000)
                        
                        timetag = SunAcc.TimeTag(None, jday=julian_day, msec=milliseconds, usec=microseconds)
                    timetags.append(timetag)
                return timetags
            else:
                # If not datetime, convert to integers and create TimeTag objects
                timetags = []
                for val in series:
                    if pd.isna(val):
                        timetag = SunAcc.TimeTag(None, jday=0, msec=0, usec=0)
                    else:
                        # Treat as seconds since epoch
                        julian_day = int(val // 86400) + 2440588
                        seconds_in_day = val % 86400
                        milliseconds = int(seconds_in_day * 1000)
                        microseconds = int((seconds_in_day * 1000) % 1000)
                        timetag = SunAcc.TimeTag(None, jday=julian_day, msec=milliseconds, usec=microseconds)
                    timetags.append(timetag)
                return timetags
        else:
            # Default to float
            return series.astype(np.float32).values
    
    def create_sun_file(self, 
                       filename: str,
                       df: pd.DataFrame,
                       file_format: str = 'compressed',
                       comment: str = '',
                       parameter_metadata: Optional[Dict[str, Dict[str, str]]] = None) -> bool:
        """
        Create a Sun file from a pandas DataFrame.
        
        Args:
            filename: Path where the Sun file should be created
            df: pandas DataFrame containing the data
            file_format: File format ('compressed', 'multitime', or 'uncompressed')
            comment: Comment to add to the file
            parameter_metadata: Dictionary mapping column names to metadata
                              Format: {'column_name': {'units': 'unit', 'description': 'desc'}}
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate inputs
            if df.empty:
                raise ValueError("DataFrame is empty")
            
            if not isinstance(df, pd.DataFrame):
                raise ValueError("Input must be a pandas DataFrame")
            
            # Determine file format
            if file_format.lower() == 'compressed':
                format_type = self.SUN_COMPRESSED
            elif file_format.lower() == 'multitime':
                format_type = self.SUN_MULTITIME
            elif file_format.lower() == 'uncompressed':
                format_type = self.SUN_UNCOMPRESSED
            else:
                raise ValueError("file_format must be 'compressed', 'multitime', or 'uncompressed'")
            
            # Check if we have datetime columns
            datetime_columns = [col for col in df.columns if pd.api.types.is_datetime64_any_dtype(df[col])]
            has_datetime = len(datetime_columns) > 0
            
            # Prepare file parameters
            n_items = len(df.columns)
            n_points = len(df)
            comment_size = len(comment.encode('utf-8')) if comment else 0
            
            # For SUN_COMPRESSED format, we need to add time parameters
            if format_type == self.SUN_COMPRESSED:
                # Add 2 extra items for relative time and TimeTag (if datetime exists)
                if has_datetime:
                    n_items += 2
                else:
                    n_items += 1  # Only relative time
            
            # Create the Sun file
            self.sunwrt = SunAcc.createSunFile(
                filename=filename,
                writemode=self.WRITE_MODE_OVERWRITE,
                commentblocksz=comment_size,
                nitems=n_items,
                npoints=n_points,
                formattype=format_type
            )
            
            if not self.sunwrt or not self.sunwrt.IsValid:
                raise RuntimeError(f"Failed to create Sun file: {SunAcc.wrtStatus()}")
            
            self.is_file_open = True
            
            # For SUN_COMPRESSED format, add time parameters first
            if format_type == self.SUN_COMPRESSED:
                # Add relative time parameter (required first)
                relative_time = np.arange(n_points, dtype=np.float32).tolist()
                status = SunAcc.addSunParm(
                    sunwrt=self.sunwrt,
                    n1='time',
                    n2='time',
                    u='seconds',
                    d='time in seconds',
                    sn=0,  # Must be 0 for relative time
                    dataID=SunAcc.DTS_FLOAT,
                    dataBuf=relative_time,
                    options=0
                )
                
                if status != 0:
                    raise RuntimeError(f"Failed to add relative time parameter (status: {status})")
                
                # Add TimeTag parameter if we have datetime data
                if has_datetime:
                    # Use the first datetime column for TimeTag
                    datetime_col = datetime_columns[0]
                    series = df[datetime_col]
                    timetags = self._convert_series_to_array(series, SunAcc.DTS_TIMETAG)
                    
                    status = SunAcc.addSunParm(
                        sunwrt=self.sunwrt,
                        n1='timetag',
                        n2='timetag',
                        u='seconds',
                        d='time in seconds',
                        sn=0,  # Must be 0 for TimeTag
                        dataID=SunAcc.DTS_TIMETAG,
                        dataBuf=timetags,
                        options=0
                    )
                    
                    if status != 0:
                        raise RuntimeError(f"Failed to add TimeTag parameter (status: {status})")
            
            # Add data parameters
            data_param_sn = 1  # Start from 1 for data parameters
            for column_name in df.columns:
                series = df[column_name]
                
                # Skip datetime columns if we already used them for TimeTag
                if format_type == self.SUN_COMPRESSED and column_name in datetime_columns:
                    continue
                
                # Get metadata for this parameter
                metadata = parameter_metadata.get(column_name, {}) if parameter_metadata else {}
                units = metadata.get('units', '')
                description = metadata.get('description', f'Parameter {column_name}')
                
                # Infer data type
                data_type = self._infer_data_type(series)
                
                # Convert data
                data_array = self._convert_series_to_array(series, data_type)
                
                # Prepare data buffer based on type
                if data_type == SunAcc.DTS_TIMETAG:
                    # For TimeTag, pass the list directly
                    data_buf = data_array
                else:
                    # For other types, convert to list
                    data_buf = data_array.tolist()
                
                # Add parameter to Sun file
                if format_type == self.SUN_MULTITIME:
                    # For MULTITIME format, we need to provide time stamps
                    if has_datetime:
                        # Use first datetime column as time stamps
                        datetime_col = datetime_columns[0]
                        time_series = df[datetime_col]
                        if pd.api.types.is_datetime64_any_dtype(time_series):
                            # Convert to relative time
                            time_stamps = (time_series - time_series.iloc[0]).dt.total_seconds().astype(np.float64).tolist()
                        else:
                            time_stamps = time_series.astype(np.float64).tolist()
                        
                        status = SunAcc.addSunParm(
                            sunwrt=self.sunwrt,
                            n1=column_name,
                            n2='',
                            u=units,
                            d=description,
                            sn=data_param_sn,
                            dataID=data_type,
                            dataBuf=data_buf,
                            indexID=SunAcc.DTS_DOUBLE,
                            indexBuf=time_stamps,
                            pCount=n_points,
                            options=SunAcc.LZH_COMPRESS if file_format.lower() == 'compressed' else 0
                        )
                    else:
                        # No datetime, use simple index
                        time_stamps = np.arange(n_points, dtype=np.float64).tolist()
                        status = SunAcc.addSunParm(
                            sunwrt=self.sunwrt,
                            n1=column_name,
                            n2='',
                            u=units,
                            d=description,
                            sn=data_param_sn,
                            dataID=data_type,
                            dataBuf=data_buf,
                            indexID=SunAcc.DTS_DOUBLE,
                            indexBuf=time_stamps,
                            pCount=n_points,
                            options=SunAcc.LZH_COMPRESS if file_format.lower() == 'compressed' else 0
                        )
                else:
                    # For other formats, add normally
                    status = SunAcc.addSunParm(
                        sunwrt=self.sunwrt,
                        n1=column_name,
                        n2='',
                        u=units,
                        d=description,
                        sn=data_param_sn,
                        dataID=data_type,
                        dataBuf=data_buf,
                        options=SunAcc.LZH_COMPRESS if file_format.lower() == 'compressed' else 0
                    )
                
                if status != 0:
                    warnings.warn(f"Warning: Failed to add parameter '{column_name}' (status: {status})")
                else:
                    data_param_sn += 1
            
            return True
            
        except Exception as e:
            print(f"Error creating Sun file: {e}")
            if self.is_file_open:
                self.close_file()
            return False
    
    def close_file(self) -> bool:
        """
        Close the currently open Sun file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.sunwrt and self.is_file_open:
                status = SunAcc.closeSunFile(self.sunwrt)
                self.is_file_open = False
                self.sunwrt = None
                return status == 0
            return True
        except Exception as e:
            print(f"Error closing Sun file: {e}")
            return False
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close_file()


def dataframe_to_sun_file(df: pd.DataFrame, 
                         filename: str,
                         file_format: str = 'compressed',
                         comment: str = '',
                         parameter_metadata: Optional[Dict[str, Dict[str, str]]] = None) -> bool:
    """
    Convenience function to convert a pandas DataFrame directly to a Sun file.
    
    Args:
        df: pandas DataFrame containing the data
        filename: Path where the Sun file should be created
        file_format: File format ('compressed', 'multitime', or 'uncompressed')
        comment: Comment to add to the file
        parameter_metadata: Dictionary mapping column names to metadata
                          Format: {'column_name': {'units': 'unit', 'description': 'desc'}}
    
    Returns:
        bool: True if successful, False otherwise
    """
    with SunFileWriter() as writer:
        return writer.create_sun_file(
            filename=filename,
            df=df,
            file_format=file_format,
            comment=comment,
            parameter_metadata=parameter_metadata
        )


# Example usage and testing
if __name__ == "__main__":
    # Create a sample DataFrame for testing
    import numpy as np
    
    # Sample data
    data = {
        'time': pd.date_range('2023-01-01', periods=100, freq='1h'),
        'temperature': np.random.normal(25, 5, 100),
        'pressure': np.random.normal(1013, 10, 100),
        'humidity': np.random.uniform(0, 100, 100),
        'sensor_id': np.random.randint(1, 10, 100)
    }
    
    df = pd.DataFrame(data)
    
    # Parameter metadata
    metadata = {
        'time': {'units': 's', 'description': 'Timestamp'},
        'temperature': {'units': '°C', 'description': 'Temperature reading'},
        'pressure': {'units': 'hPa', 'description': 'Atmospheric pressure'},
        'humidity': {'units': '%', 'description': 'Relative humidity'},
        'sensor_id': {'units': '', 'description': 'Sensor identifier'}
    }
    
    # Test the wrapper
    print("Testing Fixed SunAcc Pandas Wrapper...")
    
    # Test 1: Basic conversion with compressed format
    success = dataframe_to_sun_file(
        df=df,
        filename='fixed_test_output.sun',
        file_format='compressed',
        comment='Test Sun file created from pandas DataFrame with fixed wrapper',
        parameter_metadata=metadata
    )
    
    if success:
        print("✅ Successfully created fixed_test_output.sun")
    else:
        print("❌ Failed to create Sun file")
    
    # Test 2: Using context manager with multitime format
    print("\nTesting context manager with multitime format...")
    with SunFileWriter() as writer:
        success = writer.create_sun_file(
            filename='fixed_test_multitime.sun',
            df=df.head(50),  # Use only first 50 rows
            file_format='multitime',
            comment='Test file with context manager and multitime format',
            parameter_metadata=metadata
        )
        
        if success:
            print("✅ Successfully created fixed_test_multitime.sun using context manager")
        else:
            print("❌ Failed to create Sun file with context manager")
