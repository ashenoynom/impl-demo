#!/usr/bin/env python3
"""Create the analysis artifacts for the Ascent MC Build 47 demo.

Per https://docs.nominal.io/core/documentation/platform/simulation/analysis:

- a multi-tab, multi-run workbook (markdown overview, per-channel overlays of
  all 10 runs via comparison run groups, threshold-annotated Max-Q chart,
  histogram, and an altitude-vs-Q cartesian chart),
- a comparison workbook (per-channel run overlays driven by a full-flight
  range aggregation, plus a run-aggregate table and scatter),
- a checklist of ascent flight-limit threshold checks,
- checklist executions (data reviews) on all 10 runs.

Workbooks and checklists are not exposed as high-level create calls in the
SDK (v1.156), so this builds the conjure requests directly against
scout_notebook_api / scout_comparisonnotebook_api / scout_checks_api.

Idempotent AND convergent: objects are searched by title before creating;
when they already exist their content is updated in place (workbooks via
notebook.update, checklists by committing any checks that are missing by
title). Runs that already have a data review for this checklist are skipped.

Frontend contract notes (verified against the galaxy repo @ origin/main):
- Layouts must use "chart" panels (ChartPanelV1 + VersionedVizId into the
  contentV2 charts map); the legacy "viz" panel renders "Unknown panel type".
- A regular workbook chart draws ONLY the primary run
  (workbook.dataScope.runRids[0]) unless comparisonRunGroups lists more runs.
  Offset 0 / run anchor is correct here because all runs share the same
  absolute window (epoch 0 -> 580 s).
- A comparison workbook chart renders the "Create aggregate query" empty
  state unless rangeAggregation (dataScope + ranges condition) is set.
  groupBy=VARIABLE overlays every run's range per variable; series are
  auto-aligned to each range start. displayOption is persisted but unused.

Usage:
    python analysis_setup.py [--profile demo_space_prod]
"""

from __future__ import annotations

import argparse
import json
import uuid

from conjure_python_client import ConjureEncoder

from nominal.core import NominalClient
from nominal_api import api as nominal_api_root
from nominal_api import (
    scout_api,
    scout_channelvariables_api,
    scout_chartdefinition_api,
    scout_checks_api,
    scout_comparisonnotebook_api,
    scout_comparisonrun_api,
    scout_compute_api,
    scout_layout_api,
    scout_notebook_api,
    scout_rids_api,
    scout_workbookcommon_api,
)

PROFILE = "demo_space_prod"
SIM_NUMBER = "Ascent MC Build 47"
REF_NAME = "default"
NUM_RUNS = 10

OVERLAY_WORKBOOK_TITLE = f"{SIM_NUMBER}: trajectory overlay"
COMPARISON_WORKBOOK_TITLE = f"{SIM_NUMBER}: run comparison"
CHECKLIST_TITLE = "LV-2 ascent flight limits"

COMPARISON_CHANNELS = ["altitude_m", "dynamic_pressure_pa", "inertial_velocity_mps"]
AGGREGATE_CHANNELS = [
    ("dynamic_pressure_pa", "Max-Q [Pa]"),
    ("acceleration_mps2", "Peak accel [m/s²]"),
    ("thrust_kn", "Peak thrust [kN]"),
    ("inertial_velocity_mps", "Peak velocity [m/s]"),
    ("altitude_m", "Apogee [m]"),
]

PALETTE = {
    "altitude_m": "#4C79A8",
    "inertial_velocity_mps": "#59A14F",
    "flight_path_angle_deg": "#B07AA1",
    "dynamic_pressure_pa": "#E45756",
    "mass_kg": "#9C755F",
    "thrust_kn": "#F28E2B",
    "acceleration_mps2": "#76B7B2",
}

OVERVIEW_MARKDOWN = f"""\
# {SIM_NUMBER}

Two-stage LOX/RP-1 launch vehicle, payload deploy in LEO (~205 km, ~8.2 km/s).
One sim build, **10 dispersions**: Run 1 is the nominal case; runs 2-10
disperse stage thrust, Isp, propellant load, drag, and winds.

**How to read the charts:** the bold trace is the primary run; the faded
traces are the other dispersions (runs 2-10), overlaid via the run comparison
layer. Toggle individual runs in the *Compare* section of each chart's layer
tree.

| Tab | Contents |
|---|---|
| Trajectory | altitude, inertial velocity, flight path angle |
| Aerodynamics | Max-Q with design margins, Q distribution, Q vs altitude |
| Propulsion & loads | thrust, vehicle mass, sensed acceleration |

**Known dispersion violations** (see checklist "{CHECKLIST_TITLE}"):
Max-Q > 35 kPa on runs 3 and 10; peak thrust > 2950 kN on runs 2 and 3;
insertion apogee > 210 km on run 8.
"""


# --------------------------------------------------------------- chart helpers


def _value_axis(axis_id: str, title: str) -> scout_chartdefinition_api.ValueAxis:
    return scout_chartdefinition_api.ValueAxis(
        id=axis_id,
        title=title,
        position=scout_chartdefinition_api.AxisPosition.LEFT,
        domain_type=scout_chartdefinition_api.AxisDomainType.NUMERIC,
        display_options=scout_chartdefinition_api.AxisDisplayOptions(show_title=True),
        limit=scout_chartdefinition_api.AxisRange(),
        range=scout_chartdefinition_api.AxisRange(),
    )


def _channel_compute_node(var_name: str) -> scout_compute_api.ComputeNode:
    return scout_compute_api.ComputeNode(
        numeric=scout_compute_api.NumericSeries(raw=scout_compute_api.Reference(name=var_name))
    )


def _channel_locator(channel: str) -> scout_api.ChannelLocator:
    return scout_api.ChannelLocator(channel=channel, data_source_ref=REF_NAME, tags={})


def _comparison_run_groups(run_rids: list[str]) -> list:
    """Overlay every run after the primary (first) one, zero offset.

    All runs share the identical absolute window, so anchor=start-of-run with
    offset 0 lines them up 1:1.
    """
    if len(run_rids) < 2:
        return []
    return [
        scout_comparisonrun_api.ComparisonRunGroup(
            uuid=str(uuid.uuid4()),
            name="MC dispersions (runs 2-10)",
            offset=scout_comparisonrun_api.Offset(unit=nominal_api_root.TimeUnit.SECONDS, value=0),
            offset_anchor=scout_comparisonrun_api.OffsetAnchor(
                run=scout_comparisonrun_api.OffsetRunAnchor()
            ),
            runs=[
                scout_comparisonrun_api.ComparisonRun(run_rid=rid, enabled=True)
                for rid in run_rids[1:]
            ],
            color=None,
        )
    ]


def _line_thresholds(axis_id: str, lines: list[tuple[float, str, str, bool]]):
    """lines: (value, label, color, solid)"""
    return scout_chartdefinition_api.AxisThresholdVisualization(
        axis_id=axis_id,
        visibility=True,
        thresholds=scout_chartdefinition_api.AxisThresholdGroup(
            line_thresholds=scout_chartdefinition_api.LineThresholdGroup(
                lines=[
                    scout_chartdefinition_api.LineThreshold(
                        value=value,
                        label=label,
                        color=color,
                        line_style=(
                            scout_chartdefinition_api.ThresholdLineStyle.SOLID
                            if solid
                            else scout_chartdefinition_api.ThresholdLineStyle.DOTTED
                        ),
                    )
                    for value, label, color, solid in lines
                ],
                shading_config=scout_chartdefinition_api.ThresholdShadingConfig.NONE,
            )
        ),
    )


def _time_series_chart(
    channel: str,
    run_rids: list[str],
    title: str | None = None,
    thresholds: list[tuple[float, str, str, bool]] | None = None,
) -> scout_chartdefinition_api.VizDefinition:
    axis_id = str(uuid.uuid4())
    return scout_chartdefinition_api.VizDefinition(
        time_series=scout_chartdefinition_api.TimeSeriesChartDefinition(
            v1=scout_chartdefinition_api.TimeSeriesChartDefinitionV1(
                title=title or channel,
                comparison_run_groups=_comparison_run_groups(run_rids),
                value_axes=[_value_axis(axis_id, channel)],
                thresholds=(
                    [_line_thresholds(axis_id, thresholds)] if thresholds else []
                ),
                rows=[
                    scout_chartdefinition_api.TimeSeriesRow(
                        row_flex_size=1.0,
                        plots=[],
                        plots_v2=[
                            scout_chartdefinition_api.TimeSeriesPlotV2(
                                variable_name=channel,
                                y_axis_id=axis_id,
                                enabled=True,
                                type=scout_chartdefinition_api.TimeSeriesPlotConfig(
                                    numeric=scout_chartdefinition_api.TimeSeriesNumericPlot(
                                        color=PALETTE.get(channel, "#4C79A8"),
                                        line_style=scout_chartdefinition_api.LineStyle(
                                            v1=scout_chartdefinition_api.LineStyleV1.SOLID
                                        ),
                                    )
                                ),
                            )
                        ],
                    )
                ],
            )
        )
    )


def _markdown_chart(content: str, title: str) -> scout_chartdefinition_api.VizDefinition:
    return scout_chartdefinition_api.VizDefinition(
        markdown=scout_chartdefinition_api.MarkdownPanelDefinition(
            v1=scout_chartdefinition_api.MarkdownPanelDefinitionV1(content=content, title=title)
        )
    )


def _histogram_chart(channel: str, title: str) -> scout_chartdefinition_api.VizDefinition:
    return scout_chartdefinition_api.VizDefinition(
        histogram=scout_chartdefinition_api.HistogramChartDefinition(
            v1=scout_chartdefinition_api.HistogramChartDefinitionV1(
                title=title,
                display_settings=scout_chartdefinition_api.HistogramDisplaySettings(
                    sort=scout_chartdefinition_api.HistogramSortOrder.VALUE_ASCENDING,
                    stacked=False,
                ),
                plots=[
                    scout_chartdefinition_api.HistogramPlot(
                        variable_name=channel,
                        color=PALETTE.get(channel, "#4C79A8"),
                        enabled=True,
                    )
                ],
            )
        )
    )


def _cartesian_chart(
    x_channel: str, y_channel: str, run_rids: list[str], title: str
) -> scout_chartdefinition_api.VizDefinition:
    x_axis, y_axis = str(uuid.uuid4()), str(uuid.uuid4())
    return scout_chartdefinition_api.VizDefinition(
        cartesian=scout_chartdefinition_api.CartesianChartDefinition(
            v1=scout_chartdefinition_api.CartesianChartDefinitionV1(
                title=title,
                comparison_run_groups=_comparison_run_groups(run_rids),
                connect_points=True,
                value_axes=[
                    _value_axis(x_axis, x_channel),
                    _value_axis(y_axis, y_channel),
                ],
                plots=[
                    scout_chartdefinition_api.CartesianPlot(
                        color=PALETTE.get(y_channel, "#4C79A8"),
                        x_axis_id=x_axis,
                        x_variable_name=x_channel,
                        y_axis_id=y_axis,
                        y_variable_name=y_channel,
                        enabled=True,
                    )
                ],
            )
        )
    )


# ------------------------------------------------------------------- layouts


def _chart_panel(viz_id: str) -> scout_layout_api.Panel:
    # The app only renders "chart" panels referencing the charts map by
    # versioned id; the legacy "viz" panel type shows "Unknown panel type".
    return scout_layout_api.Panel(
        chart=scout_layout_api.ChartPanel(
            v1=scout_layout_api.ChartPanelV1(
                id=str(uuid.uuid4()),
                chart_rid=scout_rids_api.VersionedVizId(rid=viz_id, version=1),
                hide_legend=False,
            )
        )
    )


def _split(
    orientation: scout_layout_api.SplitPanelOrientation,
    side_one: scout_layout_api.Panel,
    side_two: scout_layout_api.Panel,
) -> scout_layout_api.Panel:
    return scout_layout_api.Panel(
        split=scout_layout_api.SplitPanel(
            v1=scout_layout_api.SplitPanelV1(
                id=str(uuid.uuid4()),
                orientation=orientation,
                side_one=side_one,
                side_two=side_two,
            )
        )
    )


def _split_stack(panels: list[scout_layout_api.Panel]) -> scout_layout_api.Panel:
    if len(panels) == 1:
        return panels[0]
    return _split(
        scout_layout_api.SplitPanelOrientation.HORIZONTAL, panels[0], _split_stack(panels[1:])
    )


def _tab(title: str, viz_ids: list[str]) -> scout_layout_api.SingleTab:
    return scout_layout_api.SingleTab(
        v1=scout_layout_api.SingleTabV1(
            title=title, panel=_split_stack([_chart_panel(v) for v in viz_ids])
        )
    )


def _tabbed_layout(tabs: list[scout_layout_api.SingleTab]) -> scout_layout_api.WorkbookLayout:
    return scout_layout_api.WorkbookLayout(
        v1=scout_layout_api.WorkbookLayoutV1(
            root_panel=scout_layout_api.Panel(
                tabbed=scout_layout_api.TabbedPanel(
                    v1=scout_layout_api.TabbedPanelV1(id=str(uuid.uuid4()), tabs=tabs)
                )
            )
        )
    )


# ------------------------------------------------------------ overlay workbook


def _regular_channel_variable(channel: str) -> scout_channelvariables_api.ChannelVariable:
    return scout_channelvariables_api.ChannelVariable(
        variable_name=channel,
        display_name=channel,
        compute_spec=scout_channelvariables_api.ComputeSpec(v1="{}"),
        compute_spec_v2=scout_channelvariables_api.ComputeNodeWithContext(
            compute_node=_channel_compute_node(channel),
            context=scout_channelvariables_api.WorkbookContext(
                variables={
                    channel: scout_channelvariables_api.VariableLocator(
                        series=_channel_locator(channel)
                    )
                }
            ),
        ),
    )


def _overlay_workbook_content(run_rids: list[str]):
    """Multi-tab overlay workbook. Returns (content_v2, layout)."""
    variables = [
        "altitude_m",
        "inertial_velocity_mps",
        "flight_path_angle_deg",
        "dynamic_pressure_pa",
        "mass_kg",
        "thrust_kn",
        "acceleration_mps2",
    ]
    channel_variables = {ch: _regular_channel_variable(ch) for ch in variables}

    charts: dict[str, scout_chartdefinition_api.VizDefinition] = {}

    def add(viz: scout_chartdefinition_api.VizDefinition) -> str:
        viz_id = str(uuid.uuid4())
        charts[viz_id] = viz
        return viz_id

    overview = add(_markdown_chart(OVERVIEW_MARKDOWN, "Campaign overview"))

    trajectory = [
        add(_time_series_chart("altitude_m", run_rids)),
        add(_time_series_chart("inertial_velocity_mps", run_rids)),
        add(_time_series_chart("flight_path_angle_deg", run_rids)),
    ]
    aero = [
        add(
            _time_series_chart(
                "dynamic_pressure_pa",
                run_rids,
                title="Max-Q vs design margins",
                thresholds=[
                    (35_000.0, "35 kPa design margin", "#E4A11B", False),
                    (40_000.0, "40 kPa structural limit", "#D9534F", True),
                ],
            )
        ),
        add(_histogram_chart("dynamic_pressure_pa", "Q distribution (primary run)")),
        add(_cartesian_chart("altitude_m", "dynamic_pressure_pa", run_rids, "Q vs altitude")),
    ]
    propulsion = [
        add(_time_series_chart("thrust_kn", run_rids, thresholds=[(2_950.0, "2950 kN qualification limit", "#D9534F", False)])),
        add(_time_series_chart("mass_kg", run_rids)),
        add(
            _time_series_chart(
                "acceleration_mps2",
                run_rids,
                thresholds=[(58.8, "6 g crew/structure limit", "#D9534F", True)],
            )
        ),
    ]

    layout = _tabbed_layout(
        [
            _tab("Overview", [overview]),
            _tab("Trajectory", trajectory),
            _tab("Aerodynamics", aero),
            _tab("Propulsion & loads", propulsion),
        ]
    )
    content = scout_workbookcommon_api.WorkbookContent(
        channel_variables=channel_variables, charts=charts
    )
    return scout_workbookcommon_api.UnifiedWorkbookContent(workbook=content), layout


# --------------------------------------------------------- comparison workbook


def _full_flight_aggregation(run_rids: list[str]) -> scout_comparisonnotebook_api.RangeAggregationDefinition:
    """One range per run covering the whole flight (q >= 0 is always true).

    The frontend requires a rangeAggregation with a ranges condition; there is
    no built-in "whole run" option, so use an always-true threshold.
    """
    cn = scout_comparisonnotebook_api
    sc = scout_compute_api
    ref = f"{uuid.uuid4()}.threshold.input"
    condition = cn.ComputeNodeWithContext(
        compute_node=sc.ComputeNode(
            ranges=sc.RangeSeries(
                threshold=sc.ThresholdingRanges(
                    input=sc.NumericSeries(raw=sc.Reference(name=ref)),
                    operator=sc.ThresholdOperator.GREATER_THAN_OR_EQUAL_TO,
                    threshold=sc.DoubleConstant(literal=0.0),
                    persistence_window_configuration=sc.PersistenceWindowConfiguration(
                        output_range_start=sc.OutputRangeStart(
                            first_point_matching_condition=sc.FirstPointMatchingCondition()
                        )
                    ),
                )
            )
        ),
        context=cn.ComparisonWorkbookContext(
            variables={
                ref: cn.VariableLocator(series=_channel_locator("dynamic_pressure_pa"))
            }
        ),
        supplemental_context=cn.SupplementalComparisonWorkbookContext(
            none=nominal_api_root.Empty()
        ),
    )
    return cn.RangeAggregationDefinition(
        condition=condition,
        data_scope=cn.ComparisonWorkbookDataScope(runs=list(run_rids)),
    )


def _comparison_time_series(channel: str, run_rids: list[str]) -> scout_comparisonnotebook_api.VizDefinition:
    cn = scout_comparisonnotebook_api
    axis_id = str(uuid.uuid4())
    return cn.VizDefinition(
        time_series=cn.ComparisonTimeSeriesPlotDefinition(
            v1=cn.ComparisonTimeSeriesPlotDefinitionV1(
                title=channel,
                display_option=cn.ComparisonTimeSeriesDisplayOption.CAROUSEL,
                # VARIABLE = all runs' ranges overlaid, carousel per variable.
                group_by=cn.ComparisonTimeSeriesGroupBy.VARIABLE,
                range_aggregation=_full_flight_aggregation(run_rids),
                value_axes=[_value_axis(axis_id, channel)],
                variables=[
                    cn.ComparisonTimeSeriesPlotVariable(
                        locator=cn.VariableLocator(series=_channel_locator(channel)),
                        y_axis_id=axis_id,
                    )
                ],
            )
        )
    )


def _comparison_table(run_rids: list[str]) -> scout_comparisonnotebook_api.VizDefinition:
    cn = scout_comparisonnotebook_api
    return cn.VizDefinition(
        table=cn.ComparisonTableDefinition(
            v2=cn.ComparisonTableDefinitionV2(
                title="Per-run maxima",
                range_aggregation=_full_flight_aggregation(run_rids),
                columns=[
                    cn.ComparisonTableColumn(
                        title=title,
                        locator=cn.VariableLocator(series=_channel_locator(channel)),
                        aggregation_type=cn.AggregationType(max=cn.Max()),
                        visualization_options=cn.ComparisonTableColumnVisualizationOptions(
                            format=cn.ComparisonTableColumnOptions.AXIS
                        ),
                    )
                    for channel, title in AGGREGATE_CHANNELS
                ],
            )
        )
    )


def _comparison_scatter(run_rids: list[str]) -> scout_comparisonnotebook_api.VizDefinition:
    cn = scout_comparisonnotebook_api
    charts = [
        ("dynamic_pressure_pa", "Max-Q per run"),
        ("acceleration_mps2", "Peak acceleration per run"),
    ]
    variables, axes = [], []
    for channel, _ in charts:
        x_id, y_id = str(uuid.uuid4()), str(uuid.uuid4())
        variables.append(
            cn.ComparisonScatterPlotVariable(
                x_axis_id=x_id,
                y_axis_id=y_id,
                locator=cn.VariableLocator(series=_channel_locator(channel)),
                aggregation_type=cn.AggregationType(max=cn.Max()),
            )
        )
        axes.append(
            cn.ScatterPlotValueAxes(
                x_axis=_value_axis(x_id, "run"), y_axis=_value_axis(y_id, channel)
            )
        )
    return cn.VizDefinition(
        scatter=cn.ComparisonScatterPlotDefinition(
            v1=cn.ComparisonScatterPlotDefinitionV1(
                title="Dispersion extremes",
                range_aggregation=_full_flight_aggregation(run_rids),
                variables=variables,
                axes=axes,
            )
        )
    )


def _comparison_workbook_content(run_rids: list[str]):
    """Two-tab comparison workbook. Returns (content_v2, layout)."""
    cn = scout_comparisonnotebook_api
    charts: dict[str, cn.VizDefinition] = {}

    def add(viz: cn.VizDefinition) -> str:
        viz_id = str(uuid.uuid4())
        charts[viz_id] = viz
        return viz_id

    overlays = [add(_comparison_time_series(ch, run_rids)) for ch in COMPARISON_CHANNELS]
    aggregates = [add(_comparison_table(run_rids)), add(_comparison_scatter(run_rids))]

    layout = _tabbed_layout(
        [
            _tab("Channel overlays", overlays),
            _tab("Run aggregates", aggregates),
        ]
    )
    content = cn.ComparisonWorkbookContent(channel_variables={}, charts=charts)
    return scout_workbookcommon_api.UnifiedWorkbookContent(comparison_workbook=content), layout


# ----------------------------------------------------------------- checklist


def _threshold_check(
    title: str,
    description: str,
    channel: str,
    violation_operator: scout_compute_api.ThresholdOperator,
    violation_threshold: float,
    priority: scout_api.Priority,
) -> scout_checks_api.CreateCheckRequest:
    """Check fails wherever `channel <violation_operator> <violation_threshold>` holds."""
    var_name = channel
    ranges = scout_compute_api.RangeSeries(
        threshold=scout_compute_api.ThresholdingRanges(
            input=scout_compute_api.NumericSeries(raw=scout_compute_api.Reference(name=var_name)),
            operator=violation_operator,
            threshold=scout_compute_api.DoubleConstant(literal=float(violation_threshold)),
        )
    )
    condition = scout_checks_api.UnresolvedCheckCondition(
        num_ranges_v3=scout_checks_api.UnresolvedNumRangesConditionV3(
            ranges=ranges,
            function_spec={},
            threshold=0,
            operator=scout_compute_api.ThresholdOperator.GREATER_THAN,
            variables={
                var_name: scout_checks_api.UnresolvedVariableLocator(
                    series=_channel_locator(channel)
                )
            },
        )
    )
    return scout_checks_api.CreateCheckRequest(
        title=title, description=description, priority=priority, condition=condition
    )


def _all_checks() -> list[scout_checks_api.CreateCheckRequest]:
    op = scout_compute_api.ThresholdOperator
    pr = scout_api.Priority
    return [
        _threshold_check(
            "Max dynamic pressure below 40 kPa (structural limit)",
            "Fails if dynamic_pressure_pa ever reaches 40000 Pa.",
            "dynamic_pressure_pa", op.GREATER_THAN_OR_EQUAL_TO, 40_000.0, pr.P1,
        ),
        _threshold_check(
            "Max-Q within 35 kPa design margin",
            "Fails if dynamic_pressure_pa exceeds the 35 kPa design margin. "
            "Expected to flag high-drag / tailwind dispersions.",
            "dynamic_pressure_pa", op.GREATER_THAN, 35_000.0, pr.P2,
        ),
        _threshold_check(
            "Peak sensed acceleration below 6 g",
            "Fails if acceleration_mps2 exceeds 58.8 m/s^2 (6 g) at any point.",
            "acceleration_mps2", op.GREATER_THAN, 58.8, pr.P2,
        ),
        _threshold_check(
            "Inertial velocity below 8.5 km/s",
            "Sanity bound: fails if inertial_velocity_mps exceeds 8500 m/s.",
            "inertial_velocity_mps", op.GREATER_THAN, 8_500.0, pr.P3,
        ),
        _threshold_check(
            "Peak thrust within 2950 kN qualification limit",
            "Fails if thrust_kn exceeds 2950 kN — engine qualification envelope. "
            "Expected to flag hot-thrust dispersions.",
            "thrust_kn", op.GREATER_THAN, 2_950.0, pr.P2,
        ),
        _threshold_check(
            "Insertion apogee below 210 km ceiling",
            "Fails if altitude_m exceeds 210 km — upper bound of the target insertion box.",
            "altitude_m", op.GREATER_THAN, 210_000.0, pr.P3,
        ),
        _threshold_check(
            "Stage 2 mass above 7.69 t dry-mass floor",
            "Fails if mass_kg drops below 7690 kg — would indicate propellant "
            "depletion beyond reserves.",
            "mass_kg", op.LESS_THAN, 7_690.0, pr.P1,
        ),
    ]


def make_checklist_request(
    assignee_rid: str, workspace_rid: str
) -> scout_checks_api.CreateChecklistRequest:
    return scout_checks_api.CreateChecklistRequest(
        title=CHECKLIST_TITLE,
        description=(
            "Ascent flight-limit thresholds for the LV-2 GNC simulation "
            "Monte Carlo (Ascent MC Build 47)."
        ),
        assignee_rid=assignee_rid,
        commit_message="Initial version",
        checks=[
            scout_checks_api.CreateChecklistEntryRequest(create_check=c) for c in _all_checks()
        ],
        checklist_variables=[],
        properties={"sim_number": SIM_NUMBER},
        labels=["LV-2"],
        is_published=True,
        workspace=workspace_rid,
    )


# -------------------------------------------------------------------- driver


def find_runs(client: NominalClient) -> list:
    runs = []
    for n in range(1, NUM_RUNS + 1):
        title = f"{SIM_NUMBER}: Run {n}"
        found = client.search_runs(exact_match=title)
        run = next((r for r in found if r.name == title), None)
        if run is None:
            raise SystemExit(f"Run not found: {title} — run stand_up.py first")
        runs.append(run)
    return runs


def upsert_workbook(client: NominalClient, title: str, run_rids: list[str], comparison: bool):
    """Create the workbook, or converge an existing one's content and layout."""
    if comparison:
        content_v2, layout = _comparison_workbook_content(run_rids)
        notebook_type = scout_notebook_api.NotebookType.COMPARISON_WORKBOOK
        description = (
            f"Cross-run comparison of {', '.join(COMPARISON_CHANNELS)} plus "
            f"per-run aggregates for {SIM_NUMBER}."
        )
    else:
        content_v2, layout = _overlay_workbook_content(run_rids)
        notebook_type = None
        description = (
            f"Multi-tab overlay of the {SIM_NUMBER} dispersions: trajectory, "
            "aerodynamics, and propulsion, all 10 runs per chart."
        )

    existing = None
    for wb in client.search_workbooks(exact_match=title):
        if wb.title == title:
            existing = wb
            break

    if existing is None:
        request = scout_notebook_api.CreateNotebookRequest(
            title=title,
            description=description,
            notebook_type=notebook_type,
            is_draft=False,
            state_as_json="{}",
            data_scope=scout_notebook_api.NotebookDataScope(run_rids=list(run_rids)),
            layout=layout,
            content_v2=content_v2,
            event_refs=[],
            workspace=client._clients.resolve_default_workspace_rid(),
        )
        raw = client._clients.notebook.create(client._clients.auth_header, request)
        wb = client.get_workbook(raw.rid)
        print(f"Created {'comparison ' if comparison else ''}workbook: {title} ({wb.rid})")
        return wb

    nb = client._clients.notebook.get(client._clients.auth_header, existing.rid)
    request = scout_notebook_api.UpdateNotebookRequest(
        event_refs=nb.event_refs or [],
        layout=layout,
        state_as_json="{}",
        content_v2=content_v2,
        latest_snapshot_rid=getattr(nb, "snapshot_rid", None),
    )
    client._clients.notebook.update(client._clients.auth_header, request, existing.rid)
    print(f"Updated {'comparison ' if comparison else ''}workbook in place: {title} ({existing.rid})")
    return existing


def upsert_checklist(client: NominalClient):
    """Create the checklist, or commit any checks that are missing by title."""
    existing = None
    for cl in client.search_checklists(search_text=CHECKLIST_TITLE):
        if cl.name == CHECKLIST_TITLE:
            existing = cl
            break

    workspace_rid = client._clients.resolve_default_workspace_rid()
    if existing is None:
        request = make_checklist_request(client.get_user().rid, workspace_rid)
        raw = client._clients.checklist.create(client._clients.auth_header, request)
        cl = client.get_checklist(raw.rid)
        print(f"Created checklist: {CHECKLIST_TITLE} ({cl.rid})")
        return cl

    auth = client._clients.auth_header
    raw = client._clients.checklist.get(auth, existing.rid)
    d = json.loads(json.dumps(raw, cls=ConjureEncoder))
    have = {c["check"]["title"] for c in d["checks"]}
    missing = [c for c in _all_checks() if c.title not in have]
    if missing:
        entries = [
            scout_checks_api.UpdateChecklistEntryRequest(check=c["check"]["rid"])
            for c in d["checks"]
        ] + [scout_checks_api.UpdateChecklistEntryRequest(create_check=c) for c in missing]
        client._clients.checklist.commit(
            auth,
            existing.rid,
            scout_checks_api.CommitChecklistRequest(
                checklist_variables=[],
                checks=entries,
                commit_message=f"Add {len(missing)} check(s)",
                latest_commit=d["commit"]["id"],
            ),
        )
        print(f"Committed {len(missing)} new check(s) to: {CHECKLIST_TITLE} ({existing.rid})")
    else:
        print(f"Checklist up to date ({len(have)} checks): {CHECKLIST_TITLE} ({existing.rid})")
    return existing


def execute_checklist_on_runs(client: NominalClient, checklist, runs) -> list:
    already_reviewed = set()
    try:
        for review in client.search_data_reviews(runs=[r.rid for r in runs]):
            if review.checklist_rid == checklist.rid:
                already_reviewed.add(review.run_rid)
    except Exception as e:
        print(f"Could not enumerate existing data reviews ({e}); executing on all runs")

    todo = [r for r in runs if r.rid not in already_reviewed]
    if not todo:
        print("All runs already have data reviews; nothing to execute")
        return []
    print(f"Executing checklist on {len(todo)} run(s)...")
    builder = client.data_review_builder()
    for run in todo:
        builder.execute_checklist(run.rid, checklist.rid)
    reviews = builder.initiate(wait_for_completion=True)
    print(f"Completed {len(reviews)} checklist execution(s)")
    return reviews


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=PROFILE)
    args = parser.parse_args()

    client = NominalClient.from_profile(args.profile)
    user = client.get_user()
    print(f"Authenticated as: {user.display_name} ({user.email})")

    runs = find_runs(client)
    run_rids = [r.rid for r in runs]

    overlay = upsert_workbook(client, OVERLAY_WORKBOOK_TITLE, run_rids, comparison=False)
    comparison = upsert_workbook(client, COMPARISON_WORKBOOK_TITLE, run_rids, comparison=True)
    checklist = upsert_checklist(client)
    reviews = execute_checklist_on_runs(client, checklist, runs)

    print("\n=== URLs ===")
    print(f"Overlay workbook:    {overlay.nominal_url}")
    print(f"Comparison workbook: {comparison.nominal_url}")
    print(f"Checklist:           {checklist.nominal_url}")
    for review in reviews:
        try:
            print(f"Data review: {review.rid}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
