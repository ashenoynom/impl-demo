# Batch Muon Log Processor

This script processes Muon log files in a structured folder format and uploads them to Nominal with parallel processing and checklist execution.

## Folder Structure

The script expects the following folder structure:

```
header/
    Muon_Charge_Logs_Post_Temp/    # post-test logs
        25070001.log
        25070002.log
        ...
    Muon_Charge_Logs_Pre_Temp/     # pre-test logs
        25070001.log
        25070002.log
        ...
    Muon_Temp_Cycle_Logs/          # during test logs
        25070001.log
        25070002.log
        ...
```

## Features

- **Parallel Processing**: Processes multiple log files simultaneously for faster execution
- **CSV Export**: Saves intermediate CSV files for each processed log
- **Individual Runs**: Creates separate runs for each battery SN and test type combination with proper start/stop times from log data
- **Checklist Execution**: Automatically executes checklists on all created runs
- **Data Type Fixes**: Handles problematic channels like CANA.RXERR to avoid type conflicts
- **Error Handling**: Robust error handling with detailed logging

## Usage

### Basic Usage

```bash
python batch_muon_log_processor.py /path/to/header/folder /path/to/output/csvs
```

### With Checklist Execution

```bash
# Execute different checklists for different test types
python batch_muon_log_processor.py /path/to/header/folder /path/to/output/csvs \
  --pre-post-checklist-rid your-pre-post-checklist-rid \
  --during-test-checklist-rid your-during-test-checklist-rid

# Or execute only one type of checklist
python batch_muon_log_processor.py /path/to/header/folder /path/to/output/csvs \
  --pre-post-checklist-rid your-pre-post-checklist-rid
```

### With Custom Parallel Workers

```bash
python batch_muon_log_processor.py /path/to/header/folder /path/to/output/csvs --max-workers 8
```

## Arguments

- `header_folder`: Path to the header folder containing the three log subfolders
- `output_csv_dir`: Directory where intermediate CSV files will be saved
- `--pre-post-checklist-rid`: (Optional) RID of checklist for pre-test and post-test runs
- `--during-test-checklist-rid`: (Optional) RID of checklist for during-test runs
- `--max-workers`: (Optional) Maximum number of parallel workers (default: 4)

## Configuration

Edit the following variables in the script:

```python
PROFILE_NAME = "nominal-demo@muonspace.com"  # Your Nominal profile
DATASET_NAME_PREFIX = "Muon Battery Logs"    # Prefix for dataset names

# Checklist configuration - set these to your checklist RIDs
PRE_POST_TEST_CHECKLIST_RID = None  # Checklist for pre-test and post-test runs
DURING_TEST_CHECKLIST_RID = None   # Checklist for during-test runs
```

## Output

For each battery SN and test type combination, the script will:

1. Parse the log file
2. Extract start and stop times from the log data
3. Save a CSV file: `{battery_sn}_{test_type}.csv`
4. Upload to Nominal as a separate dataset
5. Create a run with proper start/stop times from the log data
6. Return the run RID

Example output files:
- `25070001_pre_test.csv`
- `25070001_post_test.csv`
- `25070001_during_test.csv`
- `25070002_pre_test.csv`
- etc.

## Data Type Handling

The script includes special handling for problematic channels:

- **CANA.RXERR**: Forced to string type to avoid type conflicts
- **Other channels**: Automatically converted to numeric when possible, otherwise kept as strings
- **Consistent typing**: Ensures all values in a channel have the same data type

## Error Handling

- Missing log files are logged as warnings but don't stop processing
- Individual file processing errors are logged but don't stop the batch
- Thread-safe logging ensures clean output during parallel processing

## Example

```python
# Example usage in Python
import subprocess

result = subprocess.run([
    "python", "batch_muon_log_processor.py",
    "/Users/ashenoy/Downloads/header",
    "/Users/ashenoy/Downloads/csv_output",
    "--checklist-rid", "checklist_123",
    "--max-workers", "6"
], capture_output=True, text=True)

print(result.stdout)
```

## Requirements

- Python 3.7+
- pandas
- nominal (Nominal SDK)
- concurrent.futures (built-in)

## Troubleshooting

### Data Type Errors
If you encounter data type conflicts, the script now handles CANA.RXERR and similar channels by forcing them to string type.

### Memory Issues
Reduce the `--max-workers` parameter if you encounter memory issues with large log files.

### Connection Issues
Ensure your Nominal profile is correctly configured and you have internet connectivity.
