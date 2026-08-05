#!/usr/bin/env python3
"""Create the analysis artifacts for the Ascent MC Build 47 demo.

Per https://docs.nominal.io/core/documentation/platform/simulation/analysis:

- a multi-run workbook overlaying altitude_m, dynamic_pressure_pa, and
  inertial_velocity_mps across all 10 runs,
- a comparison workbook across the same runs and channels,
- a checklist of ascent flight-limit threshold checks,
- checklist executions (data reviews) on all 10 runs.

Workbooks and checklists are not exposed as high-level create calls in the
SDK (v1.156), so this builds the conjure requests directly against
scout_notebook_api / scout_comparisonnotebook_api / scout_checks_api.

Idempotent: searches by title before creating; skips runs that already have
a data review.

Usage:
    python analysis_setup.py [--profile demo_space_prod]
"""

from __future__ import annotations

import argparse
import uuid

from nominal.core import NominalClient
from nominal_api import api as nominal_api_root
from nominal_api import (
    scout_api,
    scout_channelvariables_api,
    scout_chartdefinition_api,
    scout_checks_api,
    scout_comparisonnotebook_api,
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

CHANNELS = ["altitude_m", "dynamic_pressure_pa", "inertial_velocity_mps"]
_COLORS = ["#4C79A8", "#E45756", "#59A14F"]


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


def _split_stack(panels: list[scout_layout_api.Panel]) -> scout_layout_api.Panel:
    if len(panels) == 1:
        return panels[0]
    return scout_layout_api.Panel(
        split=scout_layout_api.SplitPanel(
            v1=scout_layout_api.SplitPanelV1(
                id=str(uuid.uuid4()),
                orientation=scout_layout_api.SplitPanelOrientation.HORIZONTAL,
                side_one=panels[0],
                side_two=_split_stack(panels[1:]),
            )
        )
    )


def _layout_for_viz_ids(viz_ids: list[str]) -> scout_layout_api.WorkbookLayout:
    # The app only renders "chart" panels referencing the charts map by
    # versioned id; the legacy "viz" panel type shows "Unknown panel type".
    chart_panels = [
        scout_layout_api.Panel(
            chart=scout_layout_api.ChartPanel(
                v1=scout_layout_api.ChartPanelV1(
                    id=str(uuid.uuid4()),
                    chart_rid=scout_rids_api.VersionedVizId(rid=viz_id, version=1),
                    hide_legend=False,
                )
            )
        )
        for viz_id in viz_ids
    ]
    return scout_layout_api.WorkbookLayout(
        v1=scout_layout_api.WorkbookLayoutV1(
            root_panel=scout_layout_api.Panel(
                tabbed=scout_layout_api.TabbedPanel(
                    v1=scout_layout_api.TabbedPanelV1(
                        id=str(uuid.uuid4()),
                        tabs=[
                            scout_layout_api.SingleTab(
                                v1=scout_layout_api.SingleTabV1(
                                    title="Charts", panel=_split_stack(chart_panels)
                                )
                            )
                        ],
                    )
                )
            )
        )
    )


# ----------------------------------------------------------------- workbooks


def _regular_workbook_content(channels: list[str]):
    channel_variables, charts, viz_ids = {}, {}, []
    for i, channel in enumerate(channels):
        var_name = channel
        channel_variables[var_name] = scout_channelvariables_api.ChannelVariable(
            variable_name=var_name,
            display_name=channel,
            compute_spec=scout_channelvariables_api.ComputeSpec(v1="{}"),
            compute_spec_v2=scout_channelvariables_api.ComputeNodeWithContext(
                compute_node=_channel_compute_node(var_name),
                context=scout_channelvariables_api.WorkbookContext(
                    variables={
                        var_name: scout_channelvariables_api.VariableLocator(
                            series=_channel_locator(channel)
                        )
                    }
                ),
            ),
        )
        viz_id, axis_id = str(uuid.uuid4()), str(uuid.uuid4())
        charts[viz_id] = scout_chartdefinition_api.VizDefinition(
            time_series=scout_chartdefinition_api.TimeSeriesChartDefinition(
                v1=scout_chartdefinition_api.TimeSeriesChartDefinitionV1(
                    title=channel,
                    comparison_run_groups=[],
                    value_axes=[_value_axis(axis_id, channel)],
                    rows=[
                        scout_chartdefinition_api.TimeSeriesRow(
                            row_flex_size=1.0,
                            plots=[
                                scout_chartdefinition_api.TimeSeriesPlot(
                                    variable_name=var_name,
                                    y_axis_id=axis_id,
                                    color=_COLORS[i % len(_COLORS)],
                                    line_style=scout_chartdefinition_api.LineStyle(
                                        v1=scout_chartdefinition_api.LineStyleV1.SOLID
                                    ),
                                )
                            ],
                        )
                    ],
                )
            )
        )
        viz_ids.append(viz_id)
    content = scout_workbookcommon_api.WorkbookContent(
        channel_variables=channel_variables, charts=charts
    )
    return scout_workbookcommon_api.UnifiedWorkbookContent(workbook=content), viz_ids


def _comparison_workbook_content(channels: list[str], run_rids: list[str]):
    cn = scout_comparisonnotebook_api
    channel_variables, charts, viz_ids = {}, {}, []
    for channel in channels:
        var_name = channel
        channel_variables[var_name] = cn.ChannelVariable(
            variable_name=var_name,
            display_name=channel,
            data_scope=cn.ComparisonWorkbookDataScope(runs=list(run_rids)),
            value=cn.ComputeNodeWithContext(
                compute_node=_channel_compute_node(var_name),
                context=cn.ComparisonWorkbookContext(
                    variables={var_name: cn.VariableLocator(series=_channel_locator(channel))}
                ),
                supplemental_context=cn.SupplementalComparisonWorkbookContext(
                    none=nominal_api_root.Empty()
                ),
            ),
        )
        viz_id, axis_id = str(uuid.uuid4()), str(uuid.uuid4())
        charts[viz_id] = cn.VizDefinition(
            time_series=cn.ComparisonTimeSeriesPlotDefinition(
                v1=cn.ComparisonTimeSeriesPlotDefinitionV1(
                    title=channel,
                    display_option=cn.ComparisonTimeSeriesDisplayOption.MULTIROW,
                    group_by=cn.ComparisonTimeSeriesGroupBy.VARIABLE,
                    value_axes=[_value_axis(axis_id, channel)],
                    variables=[
                        cn.ComparisonTimeSeriesPlotVariable(
                            locator=cn.VariableLocator(comparison_workbook_variable=var_name),
                            y_axis_id=axis_id,
                        )
                    ],
                )
            )
        )
        viz_ids.append(viz_id)
    content = cn.ComparisonWorkbookContent(channel_variables=channel_variables, charts=charts)
    return scout_workbookcommon_api.UnifiedWorkbookContent(comparison_workbook=content), viz_ids


def make_workbook_request(
    title: str,
    description: str,
    run_rids: list[str],
    workspace_rid: str,
    comparison: bool,
) -> scout_notebook_api.CreateNotebookRequest:
    if comparison:
        content_v2, viz_ids = _comparison_workbook_content(CHANNELS, run_rids)
        notebook_type = scout_notebook_api.NotebookType.COMPARISON_WORKBOOK
    else:
        content_v2, viz_ids = _regular_workbook_content(CHANNELS)
        notebook_type = None
    return scout_notebook_api.CreateNotebookRequest(
        title=title,
        description=description,
        notebook_type=notebook_type,
        is_draft=False,
        state_as_json="{}",
        data_scope=scout_notebook_api.NotebookDataScope(run_rids=list(run_rids)),
        layout=_layout_for_viz_ids(viz_ids),
        content_v2=content_v2,
        event_refs=[],
        workspace=workspace_rid,
    )


# ----------------------------------------------------------------- checklist


def _threshold_check(
    title: str,
    description: str,
    channel: str,
    violation_operator: scout_compute_api.ThresholdOperator,
    violation_threshold: float,
    priority: scout_api.Priority,
) -> scout_checks_api.CreateChecklistEntryRequest:
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
    return scout_checks_api.CreateChecklistEntryRequest(
        create_check=scout_checks_api.CreateCheckRequest(
            title=title, description=description, priority=priority, condition=condition
        )
    )


def make_checklist_request(
    assignee_rid: str, workspace_rid: str
) -> scout_checks_api.CreateChecklistRequest:
    checks = [
        _threshold_check(
            title="Max dynamic pressure below 40 kPa (structural limit)",
            description="Fails if dynamic_pressure_pa ever reaches 40000 Pa.",
            channel="dynamic_pressure_pa",
            violation_operator=scout_compute_api.ThresholdOperator.GREATER_THAN_OR_EQUAL_TO,
            violation_threshold=40_000.0,
            priority=scout_api.Priority.P1,
        ),
        _threshold_check(
            title="Max-Q within 35 kPa design margin",
            description=(
                "Fails if dynamic_pressure_pa exceeds the 35 kPa design margin. "
                "Expected to flag high-drag / tailwind dispersions."
            ),
            channel="dynamic_pressure_pa",
            violation_operator=scout_compute_api.ThresholdOperator.GREATER_THAN,
            violation_threshold=35_000.0,
            priority=scout_api.Priority.P2,
        ),
        _threshold_check(
            title="Peak sensed acceleration below 6 g",
            description="Fails if acceleration_mps2 exceeds 58.8 m/s^2 (6 g) at any point.",
            channel="acceleration_mps2",
            violation_operator=scout_compute_api.ThresholdOperator.GREATER_THAN,
            violation_threshold=58.8,
            priority=scout_api.Priority.P2,
        ),
        _threshold_check(
            title="Inertial velocity below 8.5 km/s",
            description="Sanity bound: fails if inertial_velocity_mps exceeds 8500 m/s.",
            channel="inertial_velocity_mps",
            violation_operator=scout_compute_api.ThresholdOperator.GREATER_THAN,
            violation_threshold=8_500.0,
            priority=scout_api.Priority.P3,
        ),
    ]
    return scout_checks_api.CreateChecklistRequest(
        title=CHECKLIST_TITLE,
        description=(
            "Ascent flight-limit thresholds for the LV-2 GNC simulation "
            "Monte Carlo (Ascent MC Build 47)."
        ),
        assignee_rid=assignee_rid,
        commit_message="Initial version",
        checks=checks,
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


def get_or_create_workbook(client: NominalClient, title: str, run_rids: list[str], comparison: bool):
    existing = client.search_workbooks(exact_match=title)
    for wb in existing:
        if wb.title == title:
            print(f"Workbook exists, skipping create: {title} ({wb.rid})")
            return wb
    workspace_rid = client._clients.resolve_default_workspace_rid()
    request = make_workbook_request(
        title=title,
        description=(
            f"{'Cross-run comparison' if comparison else 'Multi-run overlay'} of "
            f"{', '.join(CHANNELS)} for {SIM_NUMBER}."
        ),
        run_rids=run_rids,
        workspace_rid=workspace_rid,
        comparison=comparison,
    )
    raw = client._clients.notebook.create(client._clients.auth_header, request)
    wb = client.get_workbook(raw.rid)
    print(f"Created {'comparison ' if comparison else ''}workbook: {title} ({wb.rid})")
    return wb


def get_or_create_checklist(client: NominalClient):
    for cl in client.search_checklists(search_text=CHECKLIST_TITLE):
        if cl.name == CHECKLIST_TITLE:
            print(f"Checklist exists, skipping create: {CHECKLIST_TITLE} ({cl.rid})")
            return cl
    workspace_rid = client._clients.resolve_default_workspace_rid()
    request = make_checklist_request(client.get_user().rid, workspace_rid)
    raw = client._clients.checklist.create(client._clients.auth_header, request)
    cl = client.get_checklist(raw.rid)
    print(f"Created checklist: {CHECKLIST_TITLE} ({cl.rid})")
    return cl


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

    overlay = get_or_create_workbook(client, OVERLAY_WORKBOOK_TITLE, run_rids, comparison=False)
    comparison = get_or_create_workbook(client, COMPARISON_WORKBOOK_TITLE, run_rids, comparison=True)
    checklist = get_or_create_checklist(client)
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
