import click
from pathlib import Path
from typing import Optional
import logging
import pandas as pd
import tempfile
import os
import datetime

from nominal.thirdparty.pandas import upload_dataframe
from nominal.core import Dataset
from nominal import get_default_client

logger = logging.getLogger(__name__)


def create_dataset_and_add_data(
    client, df: pd.DataFrame, name: str, timestamp_column: str, timestamp_type: str,
    description: str | None = None, wait_until_complete: bool = True
) -> Dataset:
    """Create a dataset and add data to it."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as temp_file:
        temp_path = temp_file.name
        df.to_csv(temp_file, index=False)
    
    try:
        dataset = client.create_dataset(name=name, description=description)
        dataset.add_tabular_data(
            path=temp_path,
            timestamp_column=timestamp_column,
            timestamp_type=timestamp_type,
        )
        if wait_until_complete:
            dataset.poll_until_ingestion_completed()
        return dataset
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass


def add_data_to_dataset(
    client, dataset: Dataset, df: pd.DataFrame, timestamp_column: str, timestamp_type: str,
    wait_until_complete: bool = True
) -> None:
    """Add data to an existing dataset."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as temp_file:
        temp_path = temp_file.name
        df.to_csv(temp_file, index=False)
    
    try:
        dataset.add_tabular_data(
            path=temp_path,
            timestamp_column=timestamp_column,
            timestamp_type=timestamp_type,
        )
        if wait_until_complete:
            dataset.poll_until_ingestion_completed()
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass


def inspect_tdms_timing(tdms_file, group_name, channel_name):
    """Inspect timing properties of a TDMS channel."""
    try:
        channel = tdms_file[group_name][channel_name]
        properties = channel.properties
        
        timing_info = {
            'channel_name': channel_name,
            'group_name': group_name,
            'sample_count': len(channel),
            'properties': {}
        }
        
        # Common TDMS timing properties
        timing_properties = [
            'wf_start_time', 'wf_increment', 'wf_xname', 'wf_xunit_string', 
            'wf_yunit_string', 'wf_samples', 'wf_start', 'wf_increment',
            'wf_pre_start_time', 'wf_trigger_time', 'wf_trigger_offset'
        ]
        
        for prop in timing_properties:
            if prop in properties:
                timing_info['properties'][prop] = properties[prop]
        
        return timing_info
    except Exception as e:
        return {'error': str(e)}


def create_timestamps_from_tdms_properties(channel, base_time_offset=0):
    """Create timestamps based on TDMS channel properties."""
    try:
        properties = channel.properties
        
        if 'wf_start_time' in properties and 'wf_increment' in properties:
            start_time = properties['wf_start_time']
            increment = properties['wf_increment']
            sample_count = len(channel)
            
            # Convert to Unix timestamp
            try:
                if isinstance(start_time, str) and 'T' in start_time and '-' in start_time:
                    dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    start_time = dt.timestamp()
                elif hasattr(start_time, 'timestamp'):
                    start_time = start_time.timestamp()
                elif hasattr(start_time, 'astype'):
                    start_time = start_time.astype('datetime64[s]').astype('float64')
                else:
                    start_time = float(start_time)
                
                increment = float(increment)
                timestamps = [start_time + (i * increment) for i in range(sample_count)]
                return timestamps, 'tdms_native'
                
            except (ValueError, TypeError):
                pass
        
        # Fallback: relative timestamps
        sample_count = len(channel)
        timestamps = [base_time_offset + i for i in range(sample_count)]
        return timestamps, 'fallback_relative'
        
    except Exception:
        sample_count = len(channel)
        timestamps = [base_time_offset + i for i in range(sample_count)]
        return timestamps, 'fallback_relative'


def get_tdms_start_time(tdms_file):
    """Get the earliest start time from all channels."""
    earliest_start = None
    
    for group in tdms_file.groups():
        for channel in group.channels():
            try:
                properties = channel.properties
                if 'wf_start_time' in properties:
                    start_time = properties['wf_start_time']
                    
                    try:
                        if isinstance(start_time, str) and 'T' in start_time and '-' in start_time:
                            dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                            start_time = dt.timestamp()
                        elif hasattr(start_time, 'timestamp'):
                            start_time = start_time.timestamp()
                        elif hasattr(start_time, 'astype'):
                            start_time = start_time.astype('datetime64[s]').astype('float64')
                        else:
                            start_time = float(start_time)
                        
                        if earliest_start is None or start_time < earliest_start:
                            earliest_start = start_time
                    except (ValueError, TypeError):
                        continue
            except:
                continue
    
    return earliest_start


def normalize_timestamps_to_tdms_start(timestamps, tdms_start_time):
    """Normalize timestamps to start from 0, preserving relative timing."""
    if not timestamps:
        return timestamps, 0
    
    min_time = min(timestamps)
    normalized = [t - min_time for t in timestamps]
    return normalized, min_time


@click.command("upload-tdms")
@click.argument("folder_path", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--name", "-n", help="[Optional] Base name for datasets")
@click.option("--description", "-d", help="[Optional] Description for the datasets")
@click.option("--timestamp-column", "-t", help="[Optional] Name of timestamp column in TDMS files")
@click.option("--timestamp-type", help="[Optional] Type of timestamp (e.g., 'epoch_nanoseconds')")
@click.option("--wait", is_flag=True, default=True, help="Wait for ingestion to complete")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be uploaded without actually uploading")
def upload_tdms_command(
    folder_path: Path, name: Optional[str], description: Optional[str],
    timestamp_column: Optional[str], timestamp_type: Optional[str],
    wait: bool, dry_run: bool
) -> None:
    """Upload TDMS files to Nominal, splitting by groups."""
    tdms_files = list(folder_path.glob("*.tdms"))
    
    if not tdms_files:
        click.secho(f"No .tdms files found in {folder_path}", fg="yellow")
        return
    
    click.secho(f"Found {len(tdms_files)} .tdms files:", fg="green")
    for file in tdms_files:
        click.echo(f"  - {file.name}")
    
    if dry_run:
        click.secho("Dry run mode - no files will be uploaded", fg="blue")
        return
    
    try:
        client = get_default_client()
        click.secho("Connected to Nominal", fg="green")
    except Exception as e:
        click.secho(f"Failed to connect to Nominal: {e}", fg="red")
        return
    
    successful_uploads = 0
    failed_uploads = 0
    
    for file_path in sorted(tdms_files):
        try:
            dataset_name = name or file_path.stem
            click.secho(f"Processing {file_path.name} as {dataset_name}...", fg="blue")
            
            try:
                from nptdms import TdmsFile
                
                tdms_file = TdmsFile.read(file_path)
                tdms_start_time = get_tdms_start_time(tdms_file)
                
                if tdms_start_time:
                    click.secho(f"  TDMS start time: {datetime.datetime.fromtimestamp(tdms_start_time)}", fg="green")
                else:
                    click.secho(f"  Warning: No TDMS timing found, using relative timestamps", fg="yellow")
                
                successful_groups = 0
                failed_groups = 0
                main_dataset = None
                
                for group in tdms_file.groups():
                    try:
                        click.secho(f"Processing group: {group.name} ({len(list(group.channels()))} channels)", fg="cyan")
                        
                        # Extract data from group
                        group_data = {}
                        reference_channel = None
                        for channel in group.channels():
                            try:
                                data = channel.read_data()
                                if len(data) > 0:
                                    group_data[channel.name] = data
                                    if reference_channel is None:
                                        reference_channel = channel
                            except Exception as ch_e:
                                click.secho(f"    Warning: Could not read channel {channel.name}: {ch_e}", fg="yellow")
                        
                        if group_data and reference_channel:
                            df = pd.DataFrame(group_data)
                            
                            # Create timestamps
                            timestamps, timestamp_type = create_timestamps_from_tdms_properties(reference_channel)
                            
                            if tdms_start_time and timestamps:
                                df['timestamp'] = timestamps
                                normalized_timestamps, _ = normalize_timestamps_to_tdms_start(timestamps, tdms_start_time)
                                
                                orig_start = float(timestamps[0])
                                orig_end = float(timestamps[-1])
                                norm_start = float(normalized_timestamps[0])
                                norm_end = float(normalized_timestamps[-1])
                                
                                click.secho(f"  {len(group_data)} channels, {len(df)} samples", fg="yellow")
                                click.secho(f"  Time: {orig_start:.0f} to {orig_end:.0f} Unix ({norm_start:.1f} to {norm_end:.1f}s relative)", fg="yellow")
                                click.secho(f"  Start: {datetime.datetime.fromtimestamp(orig_start)}", fg="green")
                            else:
                                df['timestamp'] = timestamps
                                click.secho(f"  {len(group_data)} channels, {len(df)} samples (relative timing)", fg="yellow")
                            
                            if main_dataset is None:
                                # Create main dataset
                                main_dataset = create_dataset_and_add_data(
                                    client=client, df=df, name=dataset_name,
                                    timestamp_column='timestamp', timestamp_type='epoch_seconds',
                                    description=f"TDMS file {file_path.name} with all groups",
                                    wait_until_complete=wait
                                )
                                click.secho(f"  ✓ Created dataset: {dataset_name} (RID: {main_dataset.rid})", fg="green")
                                successful_groups += 1
                            else:
                                # Add to existing dataset
                                add_data_to_dataset(
                                    client=client, dataset=main_dataset, df=df,
                                    timestamp_column='timestamp', timestamp_type='epoch_seconds',
                                    wait_until_complete=wait
                                )
                                click.secho(f"  ✓ Added group {group.name}", fg="green")
                                successful_groups += 1
                        else:
                            click.secho(f"  Skipping group {group.name} - no valid data", fg="yellow")
                            
                    except Exception as group_e:
                        click.secho(f"  ✗ Failed to process group {group.name}: {group_e}", fg="red")
                        failed_groups += 1
                        logger.error(f"Failed to process group {group.name}: {group_e}")
                
                click.secho(f"  Summary: {successful_groups} successful, {failed_groups} failed", fg="cyan")
                
                if successful_groups > 0:
                    click.secho(f"✓ Successfully processed {file_path.name} ({successful_groups} groups)", fg="green")
                    successful_uploads += 1
                else:
                    click.secho(f"✗ Failed to process {file_path.name} - no groups uploaded", fg="red")
                    failed_uploads += 1
                    
            except Exception as e:
                click.secho(f"✗ Failed to process {file_path.name}: {e}", fg="red")
                failed_uploads += 1
                logger.error(f"Failed to process {file_path.name}: {e}")
                
        except Exception as e:
            click.secho(f"✗ Failed to process {file_path.name}: {e}", fg="red")
            failed_uploads += 1
            logger.error(f"Failed to process {file_path.name}: {e}")
    
    # Summary
    click.secho(f"\nUpload Summary:", fg="cyan")
    click.secho(f"  Successful: {successful_uploads}", fg="green")
    click.secho(f"  Failed: {failed_uploads}", fg="red")
    click.secho(f"  Total: {len(tdms_files)}", fg="cyan")
    
    if failed_uploads > 0:
        click.secho(f"\nSome uploads failed. Check the logs for details.", fg="yellow")
        raise click.Abort()


if __name__ == "__main__":
    upload_tdms_command()
