#!/usr/bin/env python3
"""
Stream simulated satellite logs to Nominal.

This script writes made-up log messages to a Nominal dataset, attaching the same
tags used by the telemetry streamer (e.g., satellite + shell) so logs can be
filtered alongside timeseries data.
"""

import argparse
import random
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional

from nominal.core import NominalClient


# --- CONFIGURATION ---
PROFILE_NAME = "goce_streamer"  # Change to your Nominal profile name
DATASET_PREFIX = "GOCE_Streaming"  # Reuse the telemetry dataset prefix
DATASET_NAME = None  # If None, will create a dataset with prefix + timestamp

# Log streaming configuration
LOG_CHANNEL_NAME = "satellite_logs"
LOG_INTERVAL_SECONDS = 1.0  # Base interval per satellite (before speed-up)
SPEED_UP = 1.0  # Speed multiplier (1.0 = real-time, 2.0 = 2x faster)

# Multi-satellite configuration
NUM_SATELLITES = 3
NUM_SHELLS = 5
SATELLITE_TAG_KEY = "satellite"
SHELL_TAG_KEY = "shell"

# Debug configuration
PRINT_FREQUENCY = 25  # Print progress every N logs per satellite


class LogStreamer:
    """Streams simulated logs to Nominal with satellite tags."""

    def __init__(self, profile: str, dry_run: bool = False, speed_up: float = SPEED_UP):
        self.profile = profile
        self.dry_run = dry_run
        self.speed_up = speed_up
        self._active_satellites = NUM_SATELLITES
        self.random = random.Random(42)

        if not dry_run:
            self.client = NominalClient.from_profile(profile=profile)
        else:
            self.client = None
            print("🧪 DRY-RUN MODE: Skipping Nominal API calls")

    def _find_dataset_by_prefix(self, prefix: str):
        if self.dry_run:
            print(f"🧪 DRY-RUN: Would search for dataset with prefix: {prefix}")
            return None
        try:
            datasets = self.client.search_datasets(search_text=prefix)
            matching = [d for d in datasets if d.name.startswith(prefix)]
            return matching[0] if matching else None
        except Exception as exc:
            print(f"⚠️ Error searching for dataset: {exc}")
            return None

    def _get_or_create_dataset(self, dataset_name: Optional[str]):
        prefix = DATASET_PREFIX
        print(f"🔍 Searching for existing dataset with prefix: {prefix}")
        dataset = self._find_dataset_by_prefix(prefix)

        if dataset:
            print(f"✅ Found existing dataset: {dataset.name} (RID: {dataset.rid})")
            return dataset

        if self.dry_run:
            print(f"🧪 DRY-RUN: Would create dataset: {dataset_name or prefix}")
            return None

        if dataset_name is None:
            timestamp_str = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            dataset_name = f"{prefix}_{timestamp_str}"

        print(f"📊 Creating new dataset: {dataset_name}")
        dataset = self.client.create_dataset(
            name=dataset_name,
            description="Simulated GOCE satellite logs",
            prefix_tree_delimiter=".",
        )
        print(f"✅ Created dataset: {dataset.name} (RID: {dataset.rid})")
        return dataset

    def _tags_for_satellite(self, satellite_id: int) -> Dict[str, str]:
        satellites_per_shell = max(1, self._active_satellites // NUM_SHELLS)
        shell_id = (satellite_id - 1) // satellites_per_shell
        return {
            SATELLITE_TAG_KEY: f"GOCE-{satellite_id}",
            SHELL_TAG_KEY: f"shell-{shell_id + 1}",
        }

    def _generate_log_message(self, satellite_id: int, sequence: int) -> tuple[str, Dict[str, str]]:
        level = self.random.choices(
            population=["INFO", "WARN", "ERROR"],
            weights=[0.8, 0.15, 0.05],
            k=1,
        )[0]

        templates = [
            "Telemetry packet received",
            "Thermal control adjusted to {temp_c}C",
            "Reaction wheel speed set to {rpm} rpm",
            "Battery voltage stable at {voltage}V",
            "Star tracker lock {lock_status}",
            "Thruster pulse duration {pulse_ms} ms",
        ]
        template = self.random.choice(templates)
        message = template.format(
            temp_c=self.random.randint(5, 45),
            rpm=self.random.randint(1200, 4200),
            voltage=round(self.random.uniform(26.5, 29.5), 2),
            lock_status=self.random.choice(["acquired", "lost", "reacquired"]),
            pulse_ms=self.random.randint(5, 120),
        )

        tags = self._tags_for_satellite(satellite_id)
        tags.update(
            {
                "level": level,
                "sequence": str(sequence),
                "subsystem": self.random.choice(["power", "attitude", "thermal", "comms"]),
            }
        )

        return f"[{level}] {message}", tags

    def _stream_satellite_logs(self, stream, satellite_id: int):
        tags = self._tags_for_satellite(satellite_id)
        print(f"🛰️  Starting log stream for {tags[SATELLITE_TAG_KEY]} in {tags[SHELL_TAG_KEY]}")

        sequence = 0
        try:
            while True:
                sequence += 1
                message, log_tags = self._generate_log_message(satellite_id, sequence)
                timestamp = datetime.now()

                if self.dry_run:
                    print(f"🧪 LOG {log_tags[SATELLITE_TAG_KEY]}: {message} | args={log_tags}")
                else:
                    stream.enqueue(
                        channel_name=LOG_CHANNEL_NAME,
                        timestamp=timestamp,
                        value=message,
                        tags=log_tags,
                    )

                if sequence % PRINT_FREQUENCY == 0:
                    print(f"📨 {log_tags[SATELLITE_TAG_KEY]} sent {sequence} logs")

                sleep_time = max(LOG_INTERVAL_SECONDS / self.speed_up, 0.01)
                time.sleep(sleep_time)
        except KeyboardInterrupt:
            print(f"\n⏹️  Satellite {satellite_id} log streaming stopped by user")

    def start_streaming(self, dataset_name: Optional[str] = None, num_satellites: int = 1):
        self._active_satellites = num_satellites
        dataset = self._get_or_create_dataset(dataset_name)

        if self.dry_run:
            class MockStream:
                def enqueue(self, *args, **kwargs):
                    pass

            stream = MockStream()
            self._run_threads(stream, num_satellites)
            return

        threads = []
        try:
            with dataset.get_log_stream() as stream:
                for satellite_id in range(1, num_satellites + 1):
                    thread = threading.Thread(
                        target=self._stream_satellite_logs,
                        args=(stream, satellite_id),
                        daemon=True,
                    )
                    threads.append(thread)
                    thread.start()

                for thread in threads:
                    thread.join()
        except KeyboardInterrupt:
            print("\n⏹️  Log streaming stopped by user")

    def _run_threads(self, stream, num_satellites: int):
        threads = []
        for satellite_id in range(1, num_satellites + 1):
            thread = threading.Thread(
                target=self._stream_satellite_logs,
                args=(stream, satellite_id),
                daemon=True,
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream simulated GOCE-style satellite logs to Nominal.",
    )
    parser.add_argument(
        "--profile",
        default=PROFILE_NAME,
        help="Nominal config profile name (default: %(default)s)",
    )
    parser.add_argument(
        "--speed-up",
        type=float,
        default=None,
        help=f"Speed multiplier for log cadence (script default: {SPEED_UP})",
    )
    parser.add_argument(
        "--num-satellites",
        type=int,
        default=None,
        help=f"Number of concurrent satellite log streams (script default: {NUM_SATELLITES})",
    )
    parser.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Print logs without calling Nominal",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    dry_run = args.dry_run
    speed_up = args.speed_up if args.speed_up is not None else SPEED_UP
    num_satellites = args.num_satellites if args.num_satellites is not None else NUM_SATELLITES

    print("=" * 60)
    print("GOCE Log Streamer to Nominal")
    if dry_run:
        print("🧪 DRY-RUN MODE: No data will be posted to Nominal")
    print("=" * 60)
    print()

    streamer = LogStreamer(profile=args.profile, dry_run=dry_run, speed_up=speed_up)
    streamer.start_streaming(dataset_name=DATASET_NAME, num_satellites=num_satellites)


if __name__ == "__main__":
    main()
