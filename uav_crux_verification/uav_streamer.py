#!/usr/bin/env python3
"""Live UAV-1 telemetry streamer (gov staging) with commandable scenarios.

Continuously streams every channel in uav_limits.CHANNELS at STREAM_HZ into
the UAV_Verification_Streaming dataset, holding each inside its nominal band
(slow sine + noise; margins guarantee no violation trigger crossing).

Scenario protocol: the shared locked command file (command_file.py). Any
number of scenarios can be active at once — parallel requirement trees touch
disjoint channels. For each active scenario, the requirement's trigger
channels play a visible in-band test sweep for window_s seconds, then the
streamer moves the scenario into "acks". If the fault injector armed this
scenario's requirement, the middle third of the window ramps the first
trigger channel decisively past its threshold instead — the failure track.

Run:  python3 -u uav_streamer.py
"""

from __future__ import annotations

import json
import math
import pathlib
import random
import time
from datetime import datetime, timezone

from nominal.core import NominalClient

from command_file import locked_update, read_state
from staging_env import PROFILE
from uav_limits import CHANNELS, REQUIREMENT_TRIGGERS, fault_value

STREAM_HZ = 2.0
BATCH_SIZE = 200
RIDS_PATH = pathlib.Path(__file__).parent / "uav_rids.json"


class ActiveScenario:
    def __init__(self, scenario: dict, armed_fault: str | None):
        self.scenario = scenario
        self.started = time.time()
        self.mode = (
            "fault" if armed_fault == scenario.get("requirement_ext") else "nominal"
        )
        self.window = float(scenario.get("window_s", 45.0))
        self.triggers = REQUIREMENT_TRIGGERS.get(scenario.get("requirement_ext", ""), [])

    @property
    def done(self) -> bool:
        return time.time() - self.started >= self.window

    def shape(self, channel: str, base: float, amp: float) -> float | None:
        trigger_channels = [t[0] for t in self.triggers]
        if channel not in trigger_channels:
            return None
        t = time.time() - self.started
        if self.mode == "fault" and channel == trigger_channels[0]:
            third = self.window / 3.0
            if third <= t < 2 * third:
                ch, op, threshold = self.triggers[0]
                target = fault_value(ch, op, threshold)
                ramp = min(1.0, (t - third) / 2.0)  # 2 s ramp in
                return base + (target - base) * ramp
        # Visible in-band test sweep: three full cycles across the window.
        return base + 0.85 * amp * math.sin(2 * math.pi * 3.0 * t / self.window)


class ScenarioBoard:
    """Adopts new scenarios from the command file, acks finished ones."""

    def __init__(self) -> None:
        self.active: dict[str, ActiveScenario] = {}

    def poll(self) -> None:
        state = read_state()
        fault = state.get("fault") or {}
        armed_req = fault.get("requirement") if fault.get("armed") else None
        for sid, scenario in (state.get("scenarios") or {}).items():
            if sid not in self.active:
                self.active[sid] = ActiveScenario(scenario, armed_req)
                s = self.active[sid]
                print(
                    f"▶ scenario {scenario.get('requirement_ext')}/"
                    f"{scenario.get('test_case_id')} ({s.mode}, {s.window:.0f}s)"
                )
        finished = [sid for sid, s in self.active.items() if s.done]
        if finished:
            def ack(state: dict) -> None:
                for sid in finished:
                    s = self.active[sid]
                    state["scenarios"].pop(sid, None)
                    state["acks"][sid] = {
                        "id": sid,
                        "requirement_ext": s.scenario.get("requirement_ext"),
                        "test_case_id": s.scenario.get("test_case_id"),
                        "mode": s.mode,
                        "start_epoch": s.started,
                        "end_epoch": time.time(),
                    }
            locked_update(ack)
            for sid in finished:
                s = self.active.pop(sid)
                print(
                    f"■ scenario {s.scenario.get('requirement_ext')}/"
                    f"{s.scenario.get('test_case_id')} complete ({s.mode})"
                )

    def shape(self, channel: str, base: float, amp: float) -> float | None:
        for s in self.active.values():
            value = s.shape(channel, base, amp)
            if value is not None:
                return value
        return None


def main() -> None:
    rids = json.loads(RIDS_PATH.read_text())
    client = NominalClient.from_profile(PROFILE)
    dataset = client.get_dataset(rids["dataset_rid"])
    print(f"streaming {len(CHANNELS)} channels @ {STREAM_HZ} Hz → {dataset.rid}")

    rng = random.Random(1234)
    phases = {ch: rng.uniform(0, 2 * math.pi) for ch in CHANNELS}
    periods = {ch: rng.uniform(45, 120) for ch in CHANNELS}
    board = ScenarioBoard()

    with dataset.get_write_stream(batch_size=BATCH_SIZE) as stream:
        tick = 0
        while True:
            loop_start = time.time()
            stamp = datetime.now(timezone.utc)
            board.poll()
            for channel, (unit, base, amp) in CHANNELS.items():
                value = board.shape(channel, base, amp)
                if value is None:
                    slow = math.sin(
                        2 * math.pi * loop_start / periods[channel] + phases[channel]
                    )
                    value = base + amp * (0.55 * slow + 0.35 * rng.uniform(-1, 1))
                stream.enqueue(channel_name=channel, timestamp=stamp, value=value)
            tick += 1
            if tick % int(60 * STREAM_HZ) == 0:
                print(f"  … streaming ({tick} ticks, {len(board.active)} active scenarios)")
            time.sleep(max(0.0, (1.0 / STREAM_HZ) - (time.time() - loop_start)))


if __name__ == "__main__":
    main()
