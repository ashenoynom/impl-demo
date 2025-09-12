# SunAcc Pandas Wrapper

A Python wrapper for converting pandas DataFrames to Sun format files using the SunAcc library.

## Files Included

- `sunacc_pandas_wrapper.py` - Main wrapper class and functions
- `process_tdms_data.py` - Script for converting TDMS CSV data to Sun files
- `example_usage.py` - Usage examples
- `libSunAcc42` - SunAcc library file (required)
- `README.md` - This file

## Quick Start

### Basic Usage

```python
from sunacc_pandas_wrapper import dataframe_to_sun_file

# Your pandas DataFrame
df = pd.DataFrame({
    'time': pd.date_range('2023-01-01', periods=100, freq='1s'),
    'temperature': [25.0, 26.0, 27.0, ...],
    'pressure': [1013, 1012, 1011, ...]
})

# Convert to Sun file
success = dataframe_to_sun_file(df, 'output.sun')
```

### With Metadata

```python
metadata = {
    'temperature': {'units': '°C', 'description': 'Temperature reading'},
    'pressure': {'units': 'hPa', 'description': 'Pressure reading'}
}

success = dataframe_to_sun_file(
    df=df,
    filename='output.sun',
    file_format='compressed',
    parameter_metadata=metadata
)
```

### Using Context Manager

```python
from sunacc_pandas_wrapper import SunFileWriter

with SunFileWriter() as writer:
    writer.create_sun_file(df, 'output.sun')
```

## Converting TDMS Data

To convert your TDMS CSV data:

```bash
python process_tdms_data.py
```

This will create:
- `tdms_data_compressed.sun` - Compressed format
- `tdms_data_multitime.sun` - Multi-time format

## File Formats

- **compressed**: SUN_COMPRESSED format (smaller file size)
- **multitime**: SUN_MULTITIME format (includes all parameters)
- **uncompressed**: SUN_UNCOMPRESSED format

## Requirements

- Python 3.6+
- pandas
- numpy
- SunAcc library (included as libSunAcc42)

## Data Types Supported

- Numeric data (int, float) → Appropriate SunAcc numeric types
- Datetime data → DTS_TIMETAG format
- Boolean data → DTS_BYTE format
- Automatic data type inference

## Examples

Run the example script to see various usage patterns:

```bash
python example_usage.py
```

## Notes

- The SunAcc library file (`libSunAcc42`) must be in the same directory as the Python scripts
- For large datasets, consider using the compressed format for better performance
- Datetime columns are automatically converted to TimeTag format for proper time handling

