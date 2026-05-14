#!/usr/bin/env python3
"""
Stream CSV data to Nominal in real-time.

This script reads a CSV file and streams it to Nominal, making it appear as if
the data is being streamed in real-time. The timestamp column is replaced with
the current time, and the spacing between timestamps is preserved.

Features:
- Handles dynamic channel addition/removal (columns can be added/removed)
- Preserves timestamp spacing from the original data
- Continuously loops when reaching the end of the file
- Automatically detects which channels have data
- Speed-up feature: stream faster or slower than real-time (e.g., 2.0 = 2x faster)
"""

import argparse
import time
import threading
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
import pandas as pd

from nominal.core import NominalClient


SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"


def default_csv_path() -> Path:
    """Prefer the full export in-repo; fall back to the small committed sample."""
    full_csv = DATA_DIR / "goce_72h_anomalous_recent.csv"
    sample_csv = DATA_DIR / "goce_72h_anomalous_sample.csv"
    if full_csv.exists():
        return full_csv
    if sample_csv.exists():
        return sample_csv
    return full_csv


# --- CONFIGURATION ---
TIMESTAMP_COLUMN = "timestamp"
PROFILE_NAME = "goce_streamer"  # Change this to your Nominal profile name (or pass --profile)
CONNECTION_RID = None  # If None, will create a dataset instead. Set to connection RID if you have one.

# Streaming configuration
BATCH_SIZE = 100  # Number of rows to process before checking for channel changes
MAX_WAIT = timedelta(seconds=1)  # Maximum wait time for stream writes
SPEED_UP = 10.0  # Speed multiplier (1.0 = real-time, 2.0 = 2x faster, 0.5 = 2x slower)

# Multi-satellite configuration
NUM_SATELLITES = 3  # Number of satellites to simulate (each streams the same data with time shift)
SATELLITE_TAG_KEY = "satellite"  # Tag key for satellite identification
SHELL_TAG_KEY = "shell"  # Tag key for shell identification
TIME_SHIFT_BETWEEN_SATELLITES = timedelta(minutes=5)  # Time shift between each satellite

# Position phase shift configuration (for constellation simulation)
POSITION_CHANNELS = ["SST03263", "SST03264", "SST03265"]  # x, y, z position channels (ECEF)
PHASE_SHIFT_DEGREES = 180.0  # Total phase shift range in degrees (distributed among satellites)
# If PHASE_SHIFT_DEGREES = 360, satellites will be evenly distributed around a full orbit

# Shell configuration (for multiple orbital planes)
NUM_SHELLS = 5  # Number of orbital shells/planes
# Satellites are distributed across shells:
# - Shell determines orbital plane (phase shift/rotation)
# - Position within shell determines position along orbit (translation)
# Example: 25 satellites, 5 shells = 5 satellites per shell

# X/Y period scaling (for making phase difference more pronounced)
XY_PERIOD_MULTIPLIER = 1.1  # X and Y complete this many periods per Z orbit period
# Example: 2.0 means X and Y complete 2 full cycles while Z completes 1 cycle

# Spacecraft time configuration
SPACECRAFT_TIME_RESTART_INTERVAL = timedelta(hours=2)  # Time between flight computer restarts
CREATE_SPACECRAFT_TIME_DATASET = True  # Whether to create a separate dataset with spacecraft time as timestamp
SPACECRAFT_TIME_DATASET_PREFIX = "GOCE_SpacecraftTime"  # Prefix for spacecraft time dataset name

# Debug configuration
DEBUG_ORBIT_PRINT_FREQUENCY = 10  # Print debug output every N rows (set to 1 for every row, higher for less frequent)
DEBUG_ORBIT_PRINT_NEAR_ZERO = True  # Also print when Z is near 0 (equatorial crossing)


class CSVStreamer:
    """Streams CSV data to Nominal in real-time."""
    
    def __init__(self, csv_path: str, profile: str, connection_rid: Optional[str] = None, speed_up: float = 1.0, dry_run: bool = False):
        """
        Initialize the CSV streamer.
        
        Args:
            csv_path: Path to the CSV file
            profile: Nominal profile name
            connection_rid: Optional connection RID. If None, uses dataset write stream.
            speed_up: Speed multiplier (1.0 = real-time, 2.0 = 2x faster, 0.5 = 2x slower)
            dry_run: If True, skip all Nominal API calls (for testing)
        """
        self.csv_path = Path(csv_path)
        self.profile = profile
        self.connection_rid = connection_rid
        self.speed_up = speed_up
        self.dry_run = dry_run
        
        # Initialize Nominal client (skip in dry-run mode)
        if not dry_run:
            self.client = NominalClient.from_profile(profile=profile)
        else:
            self.client = None
            print("🧪 DRY-RUN MODE: Skipping Nominal API calls")
        
        # Data storage
        self.rows: List[Dict] = []
        self.timestamps: List[datetime] = []
        self.channel_columns: Set[str] = set()
        
        # Streaming state
        self.current_row_index = 0
        self.last_stream_time: Optional[datetime] = None
        self.stream_start_time: Optional[datetime] = None
        
        # Load and prepare data
        self._load_csv()
    
    def _load_csv(self):
        """Load CSV file and prepare data for streaming."""
        print(f"📂 Loading CSV file: {self.csv_path}")
        
        # Read CSV with pandas for easier handling
        df = pd.read_csv(self.csv_path, low_memory=False)
        
        if TIMESTAMP_COLUMN not in df.columns:
            raise ValueError(f"Timestamp column '{TIMESTAMP_COLUMN}' not found in CSV. Available columns: {list(df.columns)}")
        
        # Parse timestamps
        df[TIMESTAMP_COLUMN] = pd.to_datetime(df[TIMESTAMP_COLUMN])
        
        # Store rows as dictionaries
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            self.rows.append(row_dict)
            self.timestamps.append(row_dict[TIMESTAMP_COLUMN])
        
        # Identify all channel columns (all columns except timestamp)
        self.channel_columns = set(df.columns) - {TIMESTAMP_COLUMN}
        
        # Calculate total dataset duration
        if len(self.timestamps) > 1:
            self.dataset_duration = self.timestamps[-1] - self.timestamps[0]
        else:
            self.dataset_duration = timedelta(0)
        
        print(f"✅ Loaded {len(self.rows)} rows")
        print(f"📊 Found {len(self.channel_columns)} channel columns")
        print(f"⏱️  Time range: {self.timestamps[0]} to {self.timestamps[-1]}")
        print(f"⏱️  Duration: {self.dataset_duration}")
    
    def _get_time_delta(self, row_index: int, previous_row_index: Optional[int] = None) -> timedelta:
        """
        Get the time delta between the current row and the previous row.
        Handles wrap-around when going from end to beginning.
        
        Args:
            row_index: Index of the current row
            previous_row_index: Index of the previous row (if None, uses row_index - 1)
            
        Returns:
            Time delta as timedelta object
        """
        if previous_row_index is None:
            previous_row_index = row_index - 1
        
        # Handle wrap-around: if previous was at end and current is at start
        if previous_row_index >= len(self.timestamps) - 1 and row_index == 0:
            # Time delta from last row to first row (wrapping around)
            return (self.timestamps[0] - self.timestamps[-1]) + self.dataset_duration
        
        if row_index == 0:
            return timedelta(0)
        
        if previous_row_index < 0:
            previous_row_index = len(self.timestamps) - 1
        
        return self.timestamps[row_index] - self.timestamps[previous_row_index]
    
    def _calculate_orbital_velocity(self, current_row_index: int, previous_row_index: int) -> Optional[tuple]:
        """
        Calculate orbital velocity vector from position data.
        
        Args:
            current_row_index: Current row index
            previous_row_index: Previous row index
            
        Returns:
            Tuple of (vx, vy, vz) velocity vector, or None if can't calculate
        """
        if previous_row_index < 0 or previous_row_index >= len(self.rows):
            return None
        
        current_row = self.rows[current_row_index]
        previous_row = self.rows[previous_row_index]
        
        # Get positions
        if not all(ch in current_row and ch in previous_row for ch in POSITION_CHANNELS):
            return None
        
        try:
            x_curr = float(current_row[POSITION_CHANNELS[0]])
            y_curr = float(current_row[POSITION_CHANNELS[1]])
            z_curr = float(current_row[POSITION_CHANNELS[2]])
            
            x_prev = float(previous_row[POSITION_CHANNELS[0]])
            y_prev = float(previous_row[POSITION_CHANNELS[1]])
            z_prev = float(previous_row[POSITION_CHANNELS[2]])
            
            # Calculate time delta
            time_delta = self._get_time_delta(current_row_index, previous_row_index)
            delta_seconds = time_delta.total_seconds()
            
            if delta_seconds <= 0:
                return None
            
            # Calculate velocity (position change / time)
            vx = (x_curr - x_prev) / delta_seconds
            vy = (y_curr - y_prev) / delta_seconds
            vz = (z_curr - z_prev) / delta_seconds
            
            return (vx, vy, vz)
        except (ValueError, TypeError):
            return None
    
    def _apply_position_phase_shift(self, channels: Dict[str, float], satellite_id: int, current_row_index: int, previous_row_index: int, global_orbit_offset: timedelta = timedelta(0), orbit_count: int = 0) -> Dict[str, float]:
        """
        Apply phase shift to position channels to create constellation effect.
        Each satellite's position is rotated by a phase shift based on satellite_id.
        Base position data comes unchanged from source, just rotated.
        
        Args:
            channels: Dictionary of channel values
            satellite_id: Satellite ID (1, 2, 3, etc.)
            current_row_index: Current row index for velocity calculation
            previous_row_index: Previous row index for velocity calculation
            global_orbit_offset: Accumulated time offset for continuous global coverage
            orbit_count: Number of completed orbits
            
        Returns:
            Dictionary with phase-shifted position channels
        """
        # Check if we have all position channels
        if not all(ch in channels for ch in POSITION_CHANNELS):
            return channels
        
        # Get base position from source (unchanged)
        x = channels[POSITION_CHANNELS[0]]
        y = channels[POSITION_CHANNELS[1]]
        z = channels[POSITION_CHANNELS[2]]
        
        # Skip if any position is NaN
        if math.isnan(x) or math.isnan(y) or math.isnan(z):
            return channels
        
        # Calculate phase shift for this satellite
        # Distribute satellites evenly around the orbit
        satellites_per_shell = max(1, NUM_SATELLITES // NUM_SHELLS)
        shell_id = (satellite_id - 1) // satellites_per_shell
        position_in_shell = (satellite_id - 1) % satellites_per_shell
        
        # Calculate phase shift: shell phase + position within shell
        shell_phase_shift_rad = math.radians((PHASE_SHIFT_DEGREES / NUM_SHELLS) * shell_id)
        position_phase_shift_rad = math.radians((360.0 / satellites_per_shell) * position_in_shell)
        total_phase_shift_rad = shell_phase_shift_rad + position_phase_shift_rad
        
        # Apply rotation to X and Y positions (Z unchanged)
        # Calculate current azimuth
        azimuth_original = math.atan2(y, x)
        radius_xy = math.sqrt(x * x + y * y)
        
        if radius_xy == 0:
            # Zero radius, keep as-is
            x_final = x
            y_final = y
        else:
            # Apply phase shift rotation
            new_azimuth = azimuth_original + total_phase_shift_rad
            
            # Reconstruct X and Y with rotated azimuth
            x_final = radius_xy * math.cos(new_azimuth)
            y_final = radius_xy * math.sin(new_azimuth)
        
        z_final = z  # Z remains unchanged
        
        # Update channels with phase-shifted positions
        channels[POSITION_CHANNELS[0]] = x_final
        channels[POSITION_CHANNELS[1]] = y_final
        channels[POSITION_CHANNELS[2]] = z_final
        
        return channels
    
    def _get_active_channels(self, row: Dict) -> Dict[str, float]:
        """
        Extract active channels (non-null values) from a row.
        
        Args:
            row: Row dictionary
            
        Returns:
            Dictionary of channel_name -> value for non-null values
        """
        active_channels = {}
        for channel in self.channel_columns:
            value = row.get(channel)
            # Check if value is not null/empty and not a string "nan"
            if pd.notna(value) and value != '' and str(value).lower() != 'nan':
                try:
                    # Convert to float
                    float_value = float(value)
                    # Check if the float value is actually NaN (not a valid number)
                    if not (isinstance(float_value, float) and math.isnan(float_value)):
                        active_channels[channel] = float_value
                except (ValueError, TypeError):
                    # Skip if can't convert to float
                    pass
        return active_channels
    
    def _update_channel_columns(self, row: Dict):
        """
        Update the set of channel columns based on the current row.
        This allows handling dynamic channel addition/removal.
        
        Args:
            row: Row dictionary
        """
        # Check all columns in the row (except timestamp)
        current_channels = set(row.keys()) - {TIMESTAMP_COLUMN}
        
        # Add any new channels
        new_channels = current_channels - self.channel_columns
        if new_channels:
            print(f"➕ Detected new channels: {new_channels}")
            self.channel_columns.update(new_channels)
        
        # Note: We don't remove channels that disappear, as they might come back
    
    def _find_dataset_by_prefix(self, prefix: str):
        """
        Search for a dataset by prefix using NominalClient.search_datasets().
        
        Args:
            prefix: Prefix to search for (e.g., "GOCE_Streaming")
            
        Returns:
            Dataset object if found (most recent one), None otherwise
        """
        if self.dry_run:
            print(f"🧪 DRY-RUN: Would search for dataset with prefix: {prefix}")
            return None
        
        try:
            datasets = self.client.search_datasets(search_text=prefix)
            # Filter to find datasets that start with the prefix
            matching_datasets = [d for d in datasets if d.name.startswith(prefix)]
            
            if matching_datasets:
                # Return the most recent one (search_datasets should return them sorted, but we'll take the first)
                # If you want the most recent by creation time, you might need to sort by a date field
                return matching_datasets[0]
            return None
        except Exception as e:
            print(f"⚠️ Error searching for dataset: {e}")
            return None
    
    def stream_to_connection(self):
        """Stream data using a Nominal connection."""
        if not self.connection_rid:
            raise ValueError("Connection RID is required for connection-based streaming")
        
        connection = self.client.get_connection(self.connection_rid)
        print(f"🔌 Connected to Nominal connection: {self.connection_rid}")
        speed_info = f" ({self.speed_up}x speed)" if self.speed_up != 1.0 else ""
        print(f"🚀 Starting real-time streaming{speed_info}...")
        print(f"📊 Streaming {len(self.rows)} rows with {len(self.channel_columns)} channels")
        print(f"🔄 Will loop continuously when reaching end of file\n")
        
        self.stream_start_time = datetime.now()
        
        try:
            with connection.get_write_stream(max_wait=MAX_WAIT) as stream:
                while True:
                    # Check if we need to loop back to the beginning
                    if self.current_row_index >= len(self.rows):
                        print(f"\n🔄 Reached end of file. Looping back to beginning...")
                        self.current_row_index = 0
                        self.last_stream_time = None
                        self.stream_start_time = datetime.now()
                    
                    row = self.rows[self.current_row_index]
                    
                    # Update channel columns to handle dynamic additions
                    self._update_channel_columns(row)
                    
                    # Get active channels for this row
                    active_channels = self._get_active_channels(row)
                    
                    if active_channels:
                        # Calculate when this row should be streamed
                        if self.last_stream_time is None:
                            # First row - stream immediately
                            current_time = datetime.now()
                        else:
                            # Calculate time delta from original data
                            time_delta = self._get_time_delta(self.current_row_index)
                            # Wait for the appropriate time (adjusted by speed_up, cap at 60 seconds)
                            delta_seconds = time_delta.total_seconds()
                            if delta_seconds > 0:
                                # Apply speed-up factor and cap sleep time to avoid very long waits
                                sleep_time = min(delta_seconds / self.speed_up, 60.0)
                                time.sleep(sleep_time)
                            current_time = datetime.now()
                        
                        # Stream all active channels at the current time
                        stream.enqueue_from_dict(
                            timestamp=current_time,
                            channel_values=active_channels
                        )
                        
                        self.last_stream_time = current_time
                        
                        # Print progress every 100 rows
                        if self.current_row_index % 100 == 0:
                            elapsed = (current_time - self.stream_start_time).total_seconds()
                            print(f"📤 Streamed row {self.current_row_index + 1}/{len(self.rows)} "
                                  f"({len(active_channels)} channels) - Elapsed: {elapsed:.1f}s")
                    
                    self.current_row_index += 1
                    
        except KeyboardInterrupt:
            print(f"\n⏹️  Streaming stopped by user")
        except Exception as e:
            print(f"\n❌ Error during streaming: {e}")
            raise
    
    def stream_to_dataset(self, dataset_name: Optional[str] = None, num_satellites: int = 1):
        """Stream data using a Nominal dataset write stream."""
        # Create or get dataset
        if dataset_name is None:
            timestamp_str = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            dataset_name = f"GOCE_Streaming_{timestamp_str}"
        
        # Search for existing dataset by prefix
        prefix = "GOCE_Streaming"
        print(f"🔍 Searching for existing dataset with prefix: {prefix}")
        dataset = self._find_dataset_by_prefix(prefix)
        
        if dataset:
            print(f"✅ Found existing dataset: {dataset.name} (RID: {dataset.rid})")
            print(f"📤 Continuing to stream to existing dataset...")
        else:
            if self.dry_run:
                print(f"🧪 DRY-RUN: Would create dataset: {dataset_name}")
                dataset = None  # Create a mock dataset object
            else:
                print(f"📊 Creating new dataset: {dataset_name}")
                dataset = self.client.create_dataset(
                    name=dataset_name,
                    description=f"Real-time stream from {self.csv_path.name}",
                    prefix_tree_delimiter="."
                )
                print(f"✅ Created dataset: {dataset.name} (RID: {dataset.rid})")
        
        # Create spacecraft time dataset if enabled
        spacecraft_time_dataset = None
        if CREATE_SPACECRAFT_TIME_DATASET:
            sc_dataset_name = f"{SPACECRAFT_TIME_DATASET_PREFIX}_{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}"
            sc_prefix = SPACECRAFT_TIME_DATASET_PREFIX
            print(f"🔍 Searching for existing spacecraft time dataset with prefix: {sc_prefix}")
            spacecraft_time_dataset = self._find_dataset_by_prefix(sc_prefix)
            
            if spacecraft_time_dataset:
                print(f"✅ Found existing spacecraft time dataset: {spacecraft_time_dataset.name} (RID: {spacecraft_time_dataset.rid})")
            else:
                if self.dry_run:
                    print(f"🧪 DRY-RUN: Would create spacecraft time dataset: {sc_dataset_name}")
                    spacecraft_time_dataset = None
                else:
                    print(f"📊 Creating new spacecraft time dataset: {sc_dataset_name}")
                    spacecraft_time_dataset = self.client.create_dataset(
                        name=sc_dataset_name,
                        description=f"Spacecraft time stream from {self.csv_path.name} (uptime with restarts)",
                        prefix_tree_delimiter="."
                    )
                    print(f"✅ Created spacecraft time dataset: {spacecraft_time_dataset.name} (RID: {spacecraft_time_dataset.rid})")
        
        speed_info = f" ({self.speed_up}x speed)" if self.speed_up != 1.0 else ""
        print(f"🚀 Starting real-time streaming{speed_info}...")
        print(f"📊 Streaming {len(self.rows)} rows with {len(self.channel_columns)} channels")
        print(f"🛰️  Simulating {num_satellites} satellite(s)")
        if CREATE_SPACECRAFT_TIME_DATASET:
            print(f"⏱️  Spacecraft time dataset: Restart interval = {SPACECRAFT_TIME_RESTART_INTERVAL}")
        print(f"🔄 Will loop continuously when reaching end of file\n")
        
        if num_satellites > 1:
            # Multi-satellite mode: stream in parallel threads
            self._stream_multiple_satellites(dataset, num_satellites, spacecraft_time_dataset)
        else:
            # Single satellite mode: stream with tags and create asset
            start_row_index = self._calculate_starting_row_index(timedelta(0))
            thread = threading.Thread(
                target=self._stream_single_satellite,
                args=(dataset, 1, timedelta(0), "GOCE-1", start_row_index, spacecraft_time_dataset),
                daemon=True
            )
            thread.start()
            
            # Create asset and associate datasets after a short delay
            time.sleep(2)
            self._setup_assets_and_dataset(dataset, 1, spacecraft_time_dataset)
            
            # Wait for thread
            try:
                thread.join()
            except KeyboardInterrupt:
                print(f"\n⏹️  Satellite streaming stopped by user")
    
    def _stream_multiple_satellites(self, dataset, num_satellites: int, spacecraft_time_dataset=None):
        """
        Stream data for multiple satellites in parallel.
        
        Args:
            dataset: Nominal dataset object
            num_satellites: Number of satellites to simulate
            spacecraft_time_dataset: Optional dataset for spacecraft time streaming
        """
        threads = []
        
        # Calculate starting row indices for each satellite
        start_row_indices = []
        for satellite_id in range(1, num_satellites + 1):
            time_shift = timedelta(0) if satellite_id == 1 else TIME_SHIFT_BETWEEN_SATELLITES * (satellite_id - 1)
            start_row_index = self._calculate_starting_row_index(time_shift)
            start_row_indices.append(start_row_index)
        
        # Start all streaming threads simultaneously
        for satellite_id in range(1, num_satellites + 1):
            tag_value = f"GOCE-{satellite_id}"
            time_shift = timedelta(0) if satellite_id == 1 else TIME_SHIFT_BETWEEN_SATELLITES * (satellite_id - 1)
            start_row_index = start_row_indices[satellite_id - 1]
            
            thread = threading.Thread(
                target=self._stream_single_satellite,
                args=(dataset, satellite_id, time_shift, tag_value, start_row_index, spacecraft_time_dataset),
                daemon=True
            )
            threads.append(thread)
        
        # Start all threads at once
        for i, thread in enumerate(threads):
            thread.start()
            print(f"🛰️  Started satellite {i + 1} thread")
        
        # Create assets and associate datasets after a short delay (to let streaming start)
        time.sleep(2)
        self._setup_assets_and_dataset(dataset, num_satellites, spacecraft_time_dataset)
        
        # Wait for all threads
        try:
            for thread in threads:
                thread.join()
        except KeyboardInterrupt:
            print(f"\n⏹️  All satellite streaming stopped by user")
    
    def _setup_assets_and_dataset(self, dataset, num_satellites: int, spacecraft_time_dataset=None):
        """
        Create assets for each satellite and associate datasets with tag filters.
        
        Args:
            dataset: Nominal dataset object (real-time dataset)
            num_satellites: Number of satellites
            spacecraft_time_dataset: Optional spacecraft time dataset
        """
        if self.dry_run:
            print(f"\n{'='*60}")
            print("🧪 DRY-RUN: Would create assets and associate datasets...")
            print(f"{'='*60}\n")
            return
        
        print(f"\n{'='*60}")
        print("Creating assets and associating datasets...")
        print(f"{'='*60}\n")
        
        for satellite_id in range(1, num_satellites + 1):
            asset_name = f"GOCE-{satellite_id}"
            tag_value = f"GOCE-{satellite_id}"
            
            try:
                # Create or get asset
                asset_rid = self._create_or_get_asset(asset_name)
                asset = self.client.get_asset(rid=asset_rid)
                
                # Add real-time dataset to asset with filter for this satellite's tag
                print(f"📎 Adding real-time dataset to asset {asset_name} with filter: {SATELLITE_TAG_KEY}={tag_value}")
                try:
                    asset.add_dataset(
                        data_scope_name="data",
                        dataset=dataset,
                        series_tags={SATELLITE_TAG_KEY: tag_value}
                    )
                    print(f"✅ Real-time dataset added to asset {asset_name}")
                except Exception as e:
                    # Check if it's a duplicate data scope error
                    error_str = str(e)
                    if "DuplicateDataScopeNames" in error_str or "duplicate" in error_str.lower():
                        print(f"ℹ️  Real-time dataset already associated with asset {asset_name} (skipping)")
                    else:
                        # Re-raise if it's a different error
                        raise
                
                # Add spacecraft time dataset to asset if it exists
                if spacecraft_time_dataset:
                    print(f"📎 Adding spacecraft time dataset to asset {asset_name} with filter: {SATELLITE_TAG_KEY}={tag_value}")
                    try:
                        asset.add_dataset(
                            data_scope_name="spacecraft_time",
                            dataset=spacecraft_time_dataset,
                            series_tags={SATELLITE_TAG_KEY: tag_value}
                        )
                        print(f"✅ Spacecraft time dataset added to asset {asset_name}")
                    except Exception as e:
                        # Check if it's a duplicate data scope error
                        error_str = str(e)
                        if "DuplicateDataScopeNames" in error_str or "duplicate" in error_str.lower():
                            print(f"ℹ️  Spacecraft time dataset already associated with asset {asset_name} (skipping)")
                        else:
                            # Re-raise if it's a different error
                            raise
            except Exception as e:
                print(f"❌ Error processing asset {asset_name}: {e}")
    
    def start_streaming(self, dataset_name: Optional[str] = None, num_satellites: int = 1):
        """
        Start streaming data to Nominal.
        
        Args:
            dataset_name: Optional dataset name (only used if connection_rid is None)
            num_satellites: Number of satellites to simulate (default: 1)
        """
        if self.connection_rid:
            self.stream_to_connection()
        else:
            self.stream_to_dataset(dataset_name, num_satellites=num_satellites)
    
    def set_speed_up(self, speed_up: float):
        """
        Update the speed-up factor during streaming.
        
        Args:
            speed_up: Speed multiplier (1.0 = real-time, 2.0 = 2x faster, 0.5 = 2x slower)
        """
        if speed_up <= 0:
            raise ValueError("Speed-up factor must be greater than 0")
        self.speed_up = speed_up
        print(f"⚡ Speed-up updated to {speed_up}x")
    
    def _create_or_get_asset(self, asset_name: str) -> str:
        """
        Create or get an asset by name.
        
        Args:
            asset_name: Name of the asset (e.g., "GOCE-1")
            
        Returns:
            Asset RID
        """
        # Try to find existing asset by searching
        try:
            assets = self.client.search_assets(
                search_text=asset_name,
                properties={"asset_id": asset_name}
            )
            if assets:
                asset = assets[0]
                print(f"✅ Found existing asset: {asset_name} (RID: {asset.rid})")
                return asset.rid
        except Exception:
            pass
        
        # Create new asset
        try:
            asset = self.client.create_asset(
                name=asset_name,
                description=f"GOCE Satellite {asset_name}",
                properties={"asset_id": asset_name},
                labels=["Launch-1"]
            )
            print(f"✅ Created new asset: {asset_name} (RID: {asset.rid})")
            return asset.rid
        except Exception as e:
            print(f"❌ Error creating asset {asset_name}: {e}")
            raise
    
    def _calculate_starting_row_index(self, time_shift: timedelta) -> int:
        """
        Calculate which row index to start from based on time shift.
        Wraps around if time shift exceeds dataset duration.
        
        Args:
            time_shift: Time shift for this satellite
            
        Returns:
            Row index to start streaming from
        """
        if len(self.rows) == 0:
            return 0
        
        if self.dataset_duration.total_seconds() == 0:
            return 0
        
        # Convert time shift to a fraction of dataset duration (wrapping around)
        shift_seconds = time_shift.total_seconds()
        duration_seconds = self.dataset_duration.total_seconds()
        
        # Wrap around if time shift is larger than dataset duration
        shift_seconds = shift_seconds % duration_seconds if duration_seconds > 0 else 0
        
        # Find the row index that corresponds to this time shift
        # We'll find the row where the timestamp is closest to (start + shift)
        target_time = self.timestamps[0] + timedelta(seconds=shift_seconds)
        
        # Binary search or linear search for the closest row
        # For simplicity, use linear search (can be optimized if needed)
        closest_index = 0
        min_diff = abs((self.timestamps[0] - target_time).total_seconds())
        
        for i, ts in enumerate(self.timestamps):
            diff = abs((ts - target_time).total_seconds())
            if diff < min_diff:
                min_diff = diff
                closest_index = i
        
        return closest_index
    
    def _stream_single_satellite(self, dataset, satellite_id: int, time_shift: timedelta, tag_value: str, start_row_index: int = 0, spacecraft_time_dataset=None):
        """
        Stream data for a single satellite with time shift and tags.
        
        Args:
            dataset: Nominal dataset object (for real-time streaming)
            satellite_id: Satellite ID (1, 2, 3, etc.)
            time_shift: Time shift to apply to this satellite's data
            tag_value: Tag value for this satellite (e.g., "GOCE-1")
            start_row_index: Row index to start streaming from (for wrapping around)
            spacecraft_time_dataset: Optional dataset for spacecraft time streaming
        """
        # Calculate shell information
        satellites_per_shell = max(1, NUM_SATELLITES // NUM_SHELLS)
        shell_id = (satellite_id - 1) // satellites_per_shell
        shell_value = f"shell-{shell_id + 1}"
        
        print(f"🛰️  Starting satellite {satellite_id} ({tag_value}) in {shell_value} with time shift: {time_shift}, starting from row {start_row_index}")
        
        # Calculate the virtual start time (when this satellite "started" in the past)
        virtual_start_time = datetime.now() - time_shift
        
        current_row_index = start_row_index
        previous_row_index = start_row_index - 1 if start_row_index > 0 else len(self.rows) - 1
        last_stream_time: Optional[datetime] = None
        
        # Spacecraft time tracking
        spacecraft_time = timedelta(0)  # Uptime from 0
        boot_up_count = 0  # Number of restarts
        last_restart_time = timedelta(0)  # Time of last restart
        
        # Calculate cumulative time from dataset start to the starting row
        if start_row_index > 0 and start_row_index < len(self.timestamps):
            cumulative_time_from_start = self.timestamps[start_row_index] - self.timestamps[0]
        else:
            cumulative_time_from_start = timedelta(0)
        
        # Spacecraft time tracking
        spacecraft_time = timedelta(0)  # Uptime from 0
        boot_up_count = 0  # Number of restarts
        
        # Calculate shell information
        satellites_per_shell = max(1, NUM_SATELLITES // NUM_SHELLS)
        shell_id = (satellite_id - 1) // satellites_per_shell
        shell_value = f"shell-{shell_id + 1}"
        
        # Global position offset to continue orbit seamlessly across loops
        global_orbit_offset = timedelta(0)  # Accumulated offset to continue global coverage
        
        # Orbit counter for LAN precession
        orbit_count = 0  # Track which orbit we're on
        
        try:
            if self.dry_run:
                # In dry-run mode, create mock stream objects
                class MockStream:
                    def enqueue(self, *args, **kwargs):
                        pass  # Do nothing in dry-run
                stream = MockStream()
                sc_stream = MockStream() if spacecraft_time_dataset else None
            elif spacecraft_time_dataset:
                # Use both streams
                stream_ctx = dataset.get_write_stream(batch_size=1000)
                sc_stream_ctx = spacecraft_time_dataset.get_write_stream(batch_size=1000)
                stream = stream_ctx.__enter__()
                sc_stream = sc_stream_ctx.__enter__()
            else:
                # Use only real-time stream
                stream_ctx = dataset.get_write_stream(batch_size=1000)
                stream = stream_ctx.__enter__()
                sc_stream = None
            
            try:
                    while True:
                        # Wrap around row index if needed
                        if current_row_index >= len(self.rows):
                            print(f"\n🔄 Satellite {satellite_id}: Reached end of file. Continuing orbit for global coverage...")
                            previous_row_index = len(self.rows) - 1
                            current_row_index = current_row_index % len(self.rows)
                            last_stream_time = None
                            cumulative_time_from_start = timedelta(0)
                            # Continue virtual start time forward (don't reset) to maintain global coverage
                            virtual_start_time = datetime.now() - time_shift + global_orbit_offset
                            # Add dataset duration to global offset to continue orbit
                            global_orbit_offset += self.dataset_duration
                            # Increment orbit count for LAN precession
                            orbit_count += 1
                            # Reset spacecraft time on loop (simulate restart)
                            spacecraft_time = timedelta(0)
                            boot_up_count += 1
                            print(f"🔄 Satellite {satellite_id}: Flight computer restart - Boot count: {boot_up_count}, Orbit: {orbit_count}, XY period multiplier: {XY_PERIOD_MULTIPLIER}, Global orbit offset: {global_orbit_offset}")
                        
                        row = self.rows[current_row_index]
                        
                        # Get active channels for this row
                        active_channels = self._get_active_channels(row)
                        
                        # Apply phase shift to position channels to give each satellite different longitude
                        if active_channels and all(ch in active_channels for ch in POSITION_CHANNELS):
                            active_channels = self._apply_position_phase_shift(active_channels, satellite_id, current_row_index, previous_row_index, global_orbit_offset, orbit_count)
                        
                        if active_channels:
                            # Calculate when this row should be streamed
                            if last_stream_time is None:
                                # First row - use current time
                                current_time = datetime.now()
                            else:
                                # Calculate time delta from original data
                                time_delta = self._get_time_delta(current_row_index, previous_row_index)
                                # Add to cumulative time (adjusted by speed_up)
                                delta_seconds = time_delta.total_seconds()
                                if delta_seconds > 0:
                                    # Add the time delta (adjusted by speed_up) to cumulative time
                                    cumulative_time_from_start += timedelta(seconds=delta_seconds / self.speed_up)
                                    # Wait for the appropriate time (cap at 60 seconds)
                                    sleep_time = min(delta_seconds / self.speed_up, 60.0)
                                    time.sleep(sleep_time)
                                # Use current time (not virtual time) to ensure no future timestamps
                                current_time = datetime.now()
                            
                            # Ensure timestamp has microsecond precision to avoid duplicates
                            # Add a small offset based on row index to ensure uniqueness
                            current_time = current_time.replace(microsecond=(current_time.microsecond + (current_row_index % 1000)) % 1000000)
                            
                            # Update spacecraft time (uptime)
                            if last_stream_time is None:
                                # First row - spacecraft time starts at 0
                                spacecraft_time = timedelta(0)
                            else:
                                # Add the time delta to spacecraft time
                                time_delta = self._get_time_delta(current_row_index, previous_row_index)
                                delta_seconds = time_delta.total_seconds()
                                if delta_seconds > 0:
                                    spacecraft_time += timedelta(seconds=delta_seconds / self.speed_up)
                            
                            # Check for restart (simulate flight computer restart)
                            if spacecraft_time >= SPACECRAFT_TIME_RESTART_INTERVAL:
                                print(f"🔄 Satellite {satellite_id}: Flight computer restart at {spacecraft_time} - Boot count: {boot_up_count + 1}")
                                spacecraft_time = timedelta(0)
                                boot_up_count += 1
                            
                            # Stream each channel individually with tags to real-time dataset
                            for channel_name, value in active_channels.items():
                                stream.enqueue(
                                    channel_name=channel_name,
                                    timestamp=current_time,
                                    value=value,
                                    tags={
                                        SATELLITE_TAG_KEY: tag_value
                                    }
                                )
                            
                            # Stream to spacecraft time dataset if enabled
                            if sc_stream:
                                # Add spacecraft_time and boot_up_count to the data
                                sc_channels = active_channels.copy()
                                sc_channels["spacecraft_time"] = spacecraft_time.total_seconds()
                                sc_channels["boot_up_count"] = float(boot_up_count)
                                
                                # Use spacecraft_time as timestamp (epoch seconds from 0)
                                # Convert to datetime by using a base epoch time
                                base_epoch = datetime(1970, 1, 1)
                                sc_timestamp = base_epoch + spacecraft_time
                                
                                # Stream all channels with boot_up_count as tag
                                if not self.dry_run:
                                    for channel_name, value in sc_channels.items():
                                        sc_stream.enqueue(
                                            channel_name=channel_name,
                                            timestamp=sc_timestamp,
                                            value=value,
                                        tags={
                                            SATELLITE_TAG_KEY: tag_value,
                                            "boot_up_count": str(boot_up_count)
                                        }
                                        )
                            
                            last_stream_time = current_time
                            previous_row_index = current_row_index
                            
                            # Print progress every 100 rows
                            if current_row_index % 100 == 0:
                                elapsed = cumulative_time_from_start.total_seconds()
                                sc_time_str = f", SC Time: {spacecraft_time.total_seconds():.1f}s, Boot: {boot_up_count}"
                                print(f"🛰️  Satellite {satellite_id}: Streamed row {current_row_index + 1}/{len(self.rows)} "
                                      f"({len(active_channels)} channels) - Elapsed: {elapsed:.1f}s{sc_time_str}")
                        
                        current_row_index += 1
            except KeyboardInterrupt:
                print(f"\n⏹️  Satellite {satellite_id} streaming stopped by user")
            except Exception as e:
                print(f"\n❌ Error during streaming for satellite {satellite_id}: {e}")
                raise
            finally:
                # Clean up context managers if not in dry-run
                if not self.dry_run:
                    if spacecraft_time_dataset:
                        try:
                            stream_ctx.__exit__(None, None, None)
                            sc_stream_ctx.__exit__(None, None, None)
                        except:
                            pass
                    else:
                        try:
                            stream_ctx.__exit__(None, None, None)
                        except:
                            pass
        except KeyboardInterrupt:
            print(f"\n⏹️  Satellite {satellite_id} streaming stopped by user")
        except Exception as e:
            print(f"\n❌ Error during streaming for satellite {satellite_id}: {e}")
            raise


def test_phase_shift():
    """Test the phase shift calculation to verify it works correctly."""
    print("=" * 60)
    print("Testing Phase Shift Logic")
    print("=" * 60)
    print()
    
    # Simulate position data (ECEF coordinates)
    test_positions = [
        (4000000.0, 0.0, 3000000.0),  # X, Y, Z at one point
        (0.0, 4000000.0, 3000000.0),  # X, Y, Z at 90 degrees
        (-4000000.0, 0.0, 3000000.0),  # X, Y, Z at 180 degrees
        (0.0, -4000000.0, 3000000.0),  # X, Y, Z at 270 degrees
    ]
    
    # Test with different orbit counts
    for orbit_count in range(3):
        print(f"\n--- Testing Orbit {orbit_count} (XY period multiplier: {XY_PERIOD_MULTIPLIER}) ---")
        
        for i, (x, y, z) in enumerate(test_positions):
            # Simulate the period scaling calculation
            orbit_phase = (i / len(test_positions)) * 2 * math.pi  # Simulate orbit phase
            scaled_phase = orbit_phase * XY_PERIOD_MULTIPLIER
            
            # Calculate azimuth
            azimuth_original = math.degrees(math.atan2(y, x))
            radius_xy = math.sqrt(x * x + y * y)
            
            # Apply period scaling
            azimuth_offset = math.atan2(y, x) - orbit_phase
            new_azimuth_rad = azimuth_offset + scaled_phase
            x_final = radius_xy * math.cos(new_azimuth_rad)
            y_final = radius_xy * math.sin(new_azimuth_rad)
            z_final = z
            
            azimuth_final = math.degrees(math.atan2(y_final, x_final))
            azimuth_diff = azimuth_final - azimuth_original
            if azimuth_diff > 180:
                azimuth_diff -= 360
            elif azimuth_diff < -180:
                azimuth_diff += 360
            
            print(f"  Point {i+1}: Z={z:.0f} | "
                  f"Original: X={x:.0f}, Y={y:.0f}, Azimuth={azimuth_original:.1f}° | "
                  f"Final: X={x_final:.0f}, Y={y_final:.0f}, Azimuth={azimuth_final:.1f}° | "
                  f"Change: {azimuth_diff:.1f}°")
    
    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)
    print()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream GOCE CSV telemetry to Nominal with optional multi-satellite replay.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help=f"Path to CSV (default: {default_csv_path()} when --csv is omitted)",
    )
    parser.add_argument(
        "--profile",
        default=PROFILE_NAME,
        help="Nominal config profile name (default: %(default)s)",
    )
    parser.add_argument(
        "--connection-rid",
        default=None,
        dest="connection_rid",
        help="If set, stream to this connection instead of dataset mode",
    )
    parser.add_argument(
        "--speed-up",
        type=float,
        default=None,
        help=f"Playback speed multiplier (script default: {SPEED_UP})",
    )
    parser.add_argument(
        "--num-satellites",
        type=int,
        default=None,
        help=f"Number of simulated satellites (script default: {NUM_SATELLITES})",
    )
    parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Load and simulate timing without calling Nominal",
    )
    parser.add_argument(
        "--test",
        "-t",
        action="store_true",
        help="Run the phase-shift debug test and exit",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    if args.test:
        test_phase_shift()
        return

    dry_run = args.dry_run
    csv_path = args.csv.expanduser().resolve() if args.csv is not None else default_csv_path()
    speed_up = args.speed_up if args.speed_up is not None else SPEED_UP
    connection_rid = args.connection_rid if args.connection_rid is not None else CONNECTION_RID
    num_satellites = args.num_satellites if args.num_satellites is not None else NUM_SATELLITES

    print("=" * 60)
    print("GOCE CSV Streamer to Nominal")
    if dry_run:
        print("🧪 DRY-RUN MODE: No data will be posted to Nominal")
    print("=" * 60)
    print()

    if not csv_path.exists():
        print(f"❌ Error: CSV file not found: {csv_path}")
        print(f"   Place data under {DATA_DIR} or pass --csv explicitly.")
        return

    try:
        streamer = CSVStreamer(
            csv_path=str(csv_path),
            profile=args.profile,
            connection_rid=connection_rid,
            speed_up=speed_up,
            dry_run=dry_run,
        )
        streamer.start_streaming(num_satellites=num_satellites)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()

