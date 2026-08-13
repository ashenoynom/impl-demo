#!/usr/bin/env python3
"""Run-comparison workbook: GOCE-7 flight anomaly vs TVAC ground test.

Named-slot comparison per the nominal-builder skill rule (no comparison-
workbook machinery): two runs in the notebook data scope, per-run channel
variables pinned via RunChannel compute nodes (run_rid as a variable
named by the run rid), overlaid as distinct series on shared panels.

Because the flight window (live) and the ground test (2026-03-14) are
months apart in absolute time, the workbook leans on time-independent
panels — histograms (signature distributions) and cartesian V-I /
duty-power signature plots — alongside the time-series overlays (flip
the app's time axis to relative-to-run-start to overlay those).

Usage:
    python goce_runcompare_builder.py [--profile space_demo_prod]
        [--flight-run "GOCE-7 | Flight EPS anomaly investigation"]
        [--ground-run "GOCE-7 | TVAC HTR-2 anomaly replication (2026-03-14)"]
"""

from __future__ import annotations

import argparse
import uuid

from nominal.core import NominalClient
from nominal_api import (
    scout_channelvariables_api,
    scout_chartdefinition_api,
    scout_compute_api,
    scout_layout_api,
    scout_notebook_api,
    scout_rids_api,
    scout_workbookcommon_api,
)

from goce_channels import (
    BUS_CURRENT,
    BUS_TEMP,
    BUS_VOLTAGE,
    HTR_CHANNEL,
    PAYLOAD_CURRENT,
)
from goce_limits import (
    HEX_ALARM,
    LIMIT_BUS_OVERCURRENT_A,
    LIMIT_BUS_POWER_BUDGET_W,
    LIMIT_BUS_TEMP_HOT_C,
    LIMIT_BUS_UNDERVOLT_V,
    LIMIT_HTR_DUTY_LATCHED_PCT,
)

cd = scout_chartdefinition_api
sc = scout_compute_api
sl = scout_layout_api
wc = scout_workbookcommon_api

WORKBOOK_TITLE = "GOCE-7 anomaly: flight vs TVAC ground test"
REF_NAME = "data"
BUS_POWER_VAR_BASE = "eps.bus.power_w"

FLIGHT = "flight"
GROUND = "ground"
SLOT_LABEL = {FLIGHT: "Flight anomaly", GROUND: "TVAC ground test"}
SLOT_COLOR = {FLIGHT: "#E45756", GROUND: "#4C79A8"}

COMPARE_CHANNELS = [BUS_CURRENT, BUS_VOLTAGE, BUS_TEMP, HTR_CHANNEL, PAYLOAD_CURRENT]

OVERVIEW_MD = f"""\
# Flight anomaly vs TVAC ground test — GOCE-7 HTR-2 latch-up

**Question**: is the flight EPS alert the failure mode we characterized
on the bench?

| Series | Color | Source |
|---|---|---|
| Flight anomaly | red | live stream, `satellite = GOCE-7` |
| TVAC ground test | blue | FM TVAC campaign, 2026-03-14 |

**What to look for** — the latch-up signature is identical on both:

1. `tcs.htr2.duty_cycle_pct` pinned at 100% (nominal closed-loop: 6-18%)
2. `eps.bus.current_a` step of **+1.0 A** (> {LIMIT_BUS_OVERCURRENT_A} A limit)
3. `eps.bus.voltage_v` sag of **-0.25 V** (< {LIMIT_BUS_UNDERVOLT_V} V limit)
4. Bus power (V × I) plateau at ~12 W vs ~8.9 W nominal — the ~3 W
   excess is HTR-2's rated draw

The histograms and signature plots are time-independent: the flight
distribution should sit on top of the ground-test fault plateau. For
the time-series overlays, switch the time axis to *relative to run
start*.

**Ground-test conclusion (2026-03)**: latch clears with a controller
power cycle — `HTR2_PWR_CYCLE`. Recovery tau ~8 min in TVAC, faster on
orbit. Execute the corrective action via the **GOCE anomaly response**
procedure.
"""


def _var(channel: str, slot: str) -> str:
    return f"{channel}__{slot}"


def _run_channel_series(channel: str, run_rid: str) -> sc.NumericSeries:
    lit = sc.StringConstant
    return sc.NumericSeries(
        channel=sc.ChannelSeries(
            run=sc.RunChannel(
                run_rid=lit(variable=run_rid),  # variable named by the run rid
                data_scope_name=lit(literal=REF_NAME),
                channel=lit(literal=channel),
                additional_tags={},
                group_by_tags=[],
                tags_to_group_by=[],
            )
        )
    )


def _make_variable(name: str, display: str, series: sc.NumericSeries):
    return scout_channelvariables_api.ChannelVariable(
        variable_name=name,
        display_name=display,
        compute_spec=scout_channelvariables_api.ComputeSpec(v1="{}"),
        compute_spec_v2=scout_channelvariables_api.ComputeNodeWithContext(
            compute_node=sc.ComputeNode(numeric=series),
            context=scout_channelvariables_api.WorkbookContext(variables={}),
        ),
    )


def _value_axis(axis_id: str, title: str) -> cd.ValueAxis:
    return cd.ValueAxis(
        id=axis_id,
        title=title,
        position=cd.AxisPosition.LEFT,
        domain_type=cd.AxisDomainType.NUMERIC,
        display_options=cd.AxisDisplayOptions(show_title=True),
        limit=cd.AxisRange(),
        range=cd.AxisRange(),
    )


def _line_thresholds(axis_id: str, lines: list[tuple[float, str, str, bool]]):
    return cd.AxisThresholdVisualization(
        axis_id=axis_id,
        visibility=True,
        thresholds=cd.AxisThresholdGroup(
            line_thresholds=cd.LineThresholdGroup(
                lines=[
                    cd.LineThreshold(
                        value=v,
                        label=label,
                        color=color,
                        line_style=cd.ThresholdLineStyle.SOLID if solid else cd.ThresholdLineStyle.DOTTED,
                    )
                    for v, label, color, solid in lines
                ],
                shading_config=cd.ThresholdShadingConfig.NONE,
            )
        ),
    )


def _overlay_ts(
    channel_or_var: str,
    title: str,
    thresholds: list[tuple[float, str, str, bool]] | None = None,
) -> cd.VizDefinition:
    axis_id = str(uuid.uuid4())
    return cd.VizDefinition(
        time_series=cd.TimeSeriesChartDefinition(
            v1=cd.TimeSeriesChartDefinitionV1(
                title=title,
                comparison_run_groups=[],
                value_axes=[_value_axis(axis_id, title)],
                thresholds=([_line_thresholds(axis_id, thresholds)] if thresholds else []),
                rows=[
                    cd.TimeSeriesRow(
                        row_flex_size=1.0,
                        plots=[],
                        plots_v2=[
                            cd.TimeSeriesPlotV2(
                                variable_name=_var(channel_or_var, slot),
                                y_axis_id=axis_id,
                                enabled=True,
                                type=cd.TimeSeriesPlotConfig(
                                    numeric=cd.TimeSeriesNumericPlot(
                                        color=SLOT_COLOR[slot],
                                        line_style=cd.LineStyle(v1=cd.LineStyleV1.SOLID),
                                    )
                                ),
                            )
                            for slot in (FLIGHT, GROUND)
                        ],
                    )
                ],
            )
        )
    )


def _overlay_histogram(channel_or_var: str, title: str) -> cd.VizDefinition:
    return cd.VizDefinition(
        histogram=cd.HistogramChartDefinition(
            v1=cd.HistogramChartDefinitionV1(
                title=title,
                display_settings=cd.HistogramDisplaySettings(
                    sort=cd.HistogramSortOrder.VALUE_ASCENDING, stacked=False
                ),
                plots=[
                    cd.HistogramPlot(
                        variable_name=_var(channel_or_var, slot),
                        color=SLOT_COLOR[slot],
                        enabled=True,
                    )
                    for slot in (FLIGHT, GROUND)
                ],
            )
        )
    )


def _signature_plot(x: str, y: str, title: str) -> cd.VizDefinition:
    x_axis, y_axis = str(uuid.uuid4()), str(uuid.uuid4())
    return cd.VizDefinition(
        cartesian=cd.CartesianChartDefinition(
            v1=cd.CartesianChartDefinitionV1(
                title=title,
                comparison_run_groups=[],
                connect_points=False,
                value_axes=[_value_axis(x_axis, x), _value_axis(y_axis, y)],
                plots=[
                    cd.CartesianPlot(
                        color=SLOT_COLOR[slot],
                        x_axis_id=x_axis,
                        x_variable_name=_var(x, slot),
                        y_axis_id=y_axis,
                        y_variable_name=_var(y, slot),
                        enabled=True,
                    )
                    for slot in (FLIGHT, GROUND)
                ],
            )
        )
    )


def _markdown(content: str, title: str) -> cd.VizDefinition:
    return cd.VizDefinition(
        markdown=cd.MarkdownPanelDefinition(
            v1=cd.MarkdownPanelDefinitionV1(content=content, title=title)
        )
    )


def _canvas_tab(title: str, placed: list[tuple[str, float, float, float, float]]) -> sl.SingleTab:
    return sl.SingleTab(
        v1=sl.SingleTabV1(
            title=title,
            panel=sl.Panel(
                canvas=sl.CanvasLayout(
                    id=str(uuid.uuid4()),
                    objects={
                        chart_id: sl.CanvasObject(
                            panel=sl.CanvasPanel(
                                rect=sl.CanvasRect(x=x, y=y, width=w, height=h),
                                hide_legend=False,
                            )
                        )
                        for chart_id, x, y, w, h in placed
                    },
                )
            ),
        )
    )


def build_content(flight_rid: str, ground_rid: str):
    slot_rids = {FLIGHT: flight_rid, GROUND: ground_rid}

    channel_variables = {}
    for slot, rid in slot_rids.items():
        for ch in COMPARE_CHANNELS:
            channel_variables[_var(ch, slot)] = _make_variable(
                _var(ch, slot),
                f"{ch} — {SLOT_LABEL[slot]}",
                _run_channel_series(ch, rid),
            )
        # Bus power UDF per slot: P = V x I on that run's channels.
        # ProductSeries, not Multiply — galaxy's deserializer throws on
        # raw binary arithmetic nodes.
        channel_variables[_var(BUS_POWER_VAR_BASE, slot)] = _make_variable(
            _var(BUS_POWER_VAR_BASE, slot),
            f"{BUS_POWER_VAR_BASE} (V×I) — {SLOT_LABEL[slot]}",
            sc.NumericSeries(
                product=sc.ProductSeries(
                    inputs=[
                        _run_channel_series(BUS_VOLTAGE, rid),
                        _run_channel_series(BUS_CURRENT, rid),
                    ]
                )
            ),
        )

    charts: dict[str, cd.VizDefinition] = {}

    def add(viz: cd.VizDefinition) -> str:
        cid = str(uuid.uuid4())
        charts[cid] = viz
        return cid

    overview = add(_markdown(OVERVIEW_MD, "RCA comparison guide"))
    duty_ts = add(
        _overlay_ts(
            HTR_CHANNEL,
            "HTR-2 duty cycle [%] — flight vs ground",
            thresholds=[(LIMIT_HTR_DUTY_LATCHED_PCT, "latched threshold", HEX_ALARM, True)],
        )
    )
    current_ts = add(
        _overlay_ts(
            BUS_CURRENT,
            "Bus current [A] — flight vs ground",
            thresholds=[(LIMIT_BUS_OVERCURRENT_A, "overcurrent limit", HEX_ALARM, True)],
        )
    )
    voltage_ts = add(
        _overlay_ts(
            BUS_VOLTAGE,
            "Bus voltage [V] — flight vs ground",
            thresholds=[(LIMIT_BUS_UNDERVOLT_V, "undervolt limit", HEX_ALARM, True)],
        )
    )
    power_ts = add(
        _overlay_ts(
            BUS_POWER_VAR_BASE,
            "Bus power V×I [W] — flight vs ground",
            thresholds=[(LIMIT_BUS_POWER_BUDGET_W, "EPS power budget", HEX_ALARM, True)],
        )
    )
    temp_ts = add(
        _overlay_ts(
            BUS_TEMP,
            "Bus temperature [°C] — flight vs ground",
            thresholds=[(LIMIT_BUS_TEMP_HOT_C, "hot limit", HEX_ALARM, False)],
        )
    )

    current_hist = add(_overlay_histogram(BUS_CURRENT, "Bus current distribution"))
    voltage_hist = add(_overlay_histogram(BUS_VOLTAGE, "Bus voltage distribution"))
    power_hist = add(_overlay_histogram(BUS_POWER_VAR_BASE, "Bus power distribution"))
    duty_hist = add(_overlay_histogram(HTR_CHANNEL, "HTR-2 duty distribution"))
    vi_sig = add(_signature_plot(BUS_VOLTAGE, BUS_CURRENT, "V-I signature (sag under load)"))
    duty_power_sig = add(
        _signature_plot(HTR_CHANNEL, BUS_POWER_VAR_BASE, "Duty vs bus power — heater load line")
    )

    W = 1600.0
    layout = sl.WorkbookLayout(
        v1=sl.WorkbookLayoutV1(
            root_panel=sl.Panel(
                tabbed=sl.TabbedPanel(
                    v1=sl.TabbedPanelV1(
                        id=str(uuid.uuid4()),
                        tabs=[
                            _canvas_tab(
                                "Signature match",
                                [
                                    (overview, 0, 0, W / 2, 500),
                                    (duty_ts, W / 2, 0, W / 2, 250),
                                    (current_ts, W / 2, 250, W / 2, 250),
                                    (voltage_ts, 0, 500, W / 2, 260),
                                    (power_ts, W / 2, 500, W / 2, 260),
                                    (temp_ts, 0, 760, W, 240),
                                ],
                            ),
                            _canvas_tab(
                                "Distributions & signatures",
                                [
                                    (duty_hist, 0, 0, W / 2, 320),
                                    (power_hist, W / 2, 0, W / 2, 320),
                                    (current_hist, 0, 320, W / 2, 320),
                                    (voltage_hist, W / 2, 320, W / 2, 320),
                                    (vi_sig, 0, 640, W / 2, 360),
                                    (duty_power_sig, W / 2, 640, W / 2, 360),
                                ],
                            ),
                        ],
                    )
                )
            )
        )
    )

    content = wc.WorkbookContent(
        channel_variables=channel_variables,
        charts=charts,
        data_scope_inputs=wc.WorkbookDataScopeInputs(
            v1=wc.WorkbookDataScopeInputsV1(
                inputs={
                    flight_rid: wc.WorkbookDataScopeInput(
                        name=SLOT_LABEL[FLIGHT],
                        label=SLOT_LABEL[FLIGHT],
                        value=wc.DataScopeInputValue(
                            run=wc.RunDataScopeInputValue(run_rid=flight_rid)
                        ),
                        color_mode=wc.WorkbookDataScopeInputColorMode(
                            by_series=wc.BySeriesColorMode()
                        ),
                    ),
                    ground_rid: wc.WorkbookDataScopeInput(
                        name=SLOT_LABEL[GROUND],
                        label=SLOT_LABEL[GROUND],
                        value=wc.DataScopeInputValue(
                            run=wc.RunDataScopeInputValue(run_rid=ground_rid)
                        ),
                        color_mode=wc.WorkbookDataScopeInputColorMode(
                            by_series=wc.BySeriesColorMode()
                        ),
                    ),
                }
            )
        ),
    )
    return wc.UnifiedWorkbookContent(workbook=content), layout


def find_run(client: NominalClient, name: str):
    for run in client.search_runs(name_substring=name):
        if run.name == name:
            return run
    raise SystemExit(f"Run not found: {name!r} — create it first (goce_ground_setup.py)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="space_demo_prod")
    parser.add_argument("--flight-run", default="GOCE-7 | Flight EPS anomaly investigation")
    parser.add_argument("--ground-run", default="GOCE-7 | TVAC HTR-2 anomaly replication (2026-03-14)")
    args = parser.parse_args()

    client = NominalClient.from_profile(args.profile)
    c = client._clients
    print(f"Authenticated as: {client.get_user().email}")

    flight = find_run(client, args.flight_run)
    ground = find_run(client, args.ground_run)
    print(f"Flight run: {flight.rid}")
    print(f"Ground run: {ground.rid}")

    content_v2, layout = build_content(flight.rid, ground.rid)

    existing = next(
        (w for w in client.search_workbooks(exact_match=WORKBOOK_TITLE) if w.title == WORKBOOK_TITLE),
        None,
    )
    if existing is None:
        req = scout_notebook_api.CreateNotebookRequest(
            title=WORKBOOK_TITLE,
            description=(
                "RCA run comparison: GOCE-7 flight EPS anomaly vs the FM TVAC "
                "HTR-2 latch-up replication. Named-slot overlay (flight red, "
                "ground blue) with time-independent distribution and "
                "signature panels."
            ),
            is_draft=False,
            state_as_json="{}",
            layout=layout,
            content_v2=content_v2,
            data_scope=scout_notebook_api.NotebookDataScope(run_rids=[flight.rid, ground.rid]),
            event_refs=[],
            workspace=c.resolve_default_workspace_rid(),
        )
        nb = c.notebook.create(c.auth_header, req)
        wb = client.get_workbook(nb.rid)
        print(f"Created workbook: {WORKBOOK_TITLE} ({nb.rid})")
    else:
        nb_raw = c.notebook.get(c.auth_header, existing.rid)
        c.notebook.update(
            c.auth_header,
            scout_notebook_api.UpdateNotebookRequest(
                event_refs=nb_raw.event_refs or [],
                layout=layout,
                state_as_json="{}",
                content_v2=content_v2,
                latest_snapshot_rid=getattr(nb_raw, "snapshot_rid", None),
            ),
            existing.rid,
        )
        wb = existing
        print(f"Updated workbook in place: {WORKBOOK_TITLE} ({existing.rid})")

    check = c.notebook.get(c.auth_header, wb.rid)
    n_charts = len(check.content_v2.workbook.charts) if check.content_v2 else 0
    print(f"Verified: {n_charts} charts on server")
    print(f"\nWorkbook URL: {wb.nominal_url}")


if __name__ == "__main__":
    main()
