#!/usr/bin/env python3
"""Create the GOCE constellation workbook (25 satellites) in Nominal.

Builds an asset-scoped, multi-tab workbook over the GOCE-1..GOCE-N assets
created by goce_csv_streamer.py:

- Overview: markdown explaining the constellation demo,
- Earth view: geo map with one live ground track per satellite (latitude /
  longitude channels) plus a fleet altitude overlay,
- Orbit: ECEF position overlays showing the shell/plane phase spread,
- Thermal / Power & sensors: fleet overlays of bus telemetry.

Workbooks are not exposed as high-level create calls in the SDK (v1.156), so
this builds the conjure requests directly against scout_notebook_api, in the
same style as ascent_mc/analysis_setup.py.

Frontend contract notes (same conventions verified for the ascent demo):
- Layouts must use "chart" panels (ChartPanelV1 + VersionedVizId into the
  contentV2 charts map); the legacy "viz" panel renders "Unknown panel type".
- Channel variables are pinned to one asset via an AssetChannel compute node
  whose assetRid is a *variable* named by the asset rid (mirrors the
  RunChannel runRid convention); the compute context resolves it.
- The asset data scope name is "data" (set by the streamer's
  asset.add_dataset(data_scope_name="data", series_tags={satellite: GOCE-n})),
  so per-satellite tag filtering happens in the asset scope itself.

Idempotent AND convergent: the workbook is searched by title before creating;
if it already exists its content and layout are updated in place.

Usage:
    python constellation_workbook.py [--profile goce_streamer] [--num-satellites 25]
"""

from __future__ import annotations

import argparse
import colorsys
import uuid

from nominal.core import NominalClient
from nominal_api import (
    scout_chartdefinition_api,
    scout_channelvariables_api,
    scout_compute_api,
    scout_layout_api,
    scout_notebook_api,
    scout_rids_api,
    scout_workbookcommon_api,
)

from goce_channels import (
    ACCEL_CHANNELS,
    BUS_CURRENT,
    BUS_CURRENT_CHANNELS,
    BUS_TEMP,
    BUS_TEMP_CHANNELS,
    BUS_VOLTAGE,
    BUS_VOLTAGE_CHANNELS,
    GEO_ALT_CHANNEL,
    GEO_LAT_CHANNEL,
    GEO_LON_CHANNEL,
    HTR_CHANNEL,
    LOG_CHANNEL,
    MAG_CHANNELS,
    PANEL_TEMP_CHANNELS,
    PAYLOAD_CURRENT,
    POWER_RAIL_CHANNELS,
    STRUCT_TEMP_CHANNELS,
    VELOCITY_CHANNELS,
    WHEEL_CHANNELS,
)
from goce_limits import CHANNEL_THRESHOLDS, FAULT_SATELLITE

PROFILE = "goce_streamer"
NUM_SATELLITES = 25
NUM_SHELLS = 5
DATA_SCOPE_NAME = "data"  # set by goce_csv_streamer._setup_assets_and_dataset

WORKBOOK_TITLE = f"GOCE constellation: {NUM_SATELLITES}-satellite fleet"

ORBIT_CHANNELS = [
    ("gnc.orbit.ecef_x_m", "ECEF X position [m]"),
    ("gnc.orbit.ecef_y_m", "ECEF Y position [m]"),
    ("gnc.orbit.ecef_z_m", "ECEF Z position [m]"),
]
# Densest temperature-like channels in the replay (0.5-0.8 s wall interval at
# 10x), so the fleet overlay paints immediately even in a 30 s live window;
# the tcs.structure channels only sample every 32 s of sim time.
THERMAL_CHANNELS = [
    (BUS_TEMP, "Bus temperature [°C]"),
    ("tcs.avionics.gps_temp_c", "GPS receiver temperature [°C]"),
    ("tcs.avionics.xband_temp_c", "X-band transmitter temperature [°C]"),
]
POWER_CHANNELS = [
    (BUS_VOLTAGE, "Main bus voltage [V]"),
    (BUS_CURRENT, "Main bus current [A]"),
    (HTR_CHANNEL, "HTR-2 heater duty cycle [%]"),
    ("aocs.mag.bx_nt", "Magnetometer Bx [nT]"),
]

# Fleet status table: one row per satellite, these channels as columns.
FLEET_STATUS_CHANNELS = [BUS_VOLTAGE, BUS_CURRENT, BUS_TEMP, HTR_CHANNEL]
FLEET_STATUS_HEADERS = ["Bus V [V]", "Bus I [A]", "Bus temp [°C]", "HTR-2 duty [%]"]

# Bus-health checklist shown in checklist panels (goce_deepdive_builder).
CHECKLIST_RID = "ri.scout.cerulean-staging.check-collection.25800248-86a1-49f5-8c52-d6f91f26f992"

OVERVIEW_MARKDOWN = f"""\
# GOCE constellation — live fleet view

**{NUM_SATELLITES} satellites** streaming live telemetry, arranged
Starlink-style in **{NUM_SHELLS} orbital planes** ({NUM_SATELLITES // NUM_SHELLS}
satellites per plane, 53° inclination, ~550 km altitude). Data is a GOCE
telemetry replay: every satellite carries the full bus telemetry set, with
per-satellite gain/drift variance so the fleet disperses realistically.

**How to read the tabs:**

| Tab | Contents |
|---|---|
| Fleet status | Live health grid: one row per satellite, threshold-colored (green = nominal, yellow = warning, red = alarm) |
| Earth view | Live ground track per satellite + fleet altitude overlay |
| Orbit | ECEF position overlays — the plane/phase spread of the constellation |
| Thermal | Bus temperature overlays across the fleet |
| EPS & heater | Bus voltage/current and HTR-2 heater duty across the fleet |

Channels use the hierarchical namespace `system.subsystem.measure`
(`eps.bus.current_a`, `tcs.htr2.duty_cycle_pct`, ...). If a satellite
trips an EPS alarm here, drill down via its zoom-down workbook and the
**GOCE-7: bus health deep-dive** RCA flow.

Every chart overlays all {NUM_SATELLITES} satellites, one colored trace per
satellite (GOCE-1 is the nominal reference). Toggle individual satellites from
the chart's layer list. Assets `GOCE-1` … `GOCE-{NUM_SATELLITES}` each scope
the shared streaming dataset filtered to their `satellite` tag.
"""


def sat_color(n: int) -> str:
    """Distinct, stable color per satellite (golden-angle hue spacing)."""
    hue = (n * 0.618033988749895) % 1.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.75)
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


def _var_name(channel: str, sat_no: int) -> str:
    return f"{channel}__s{sat_no}"


def _km_var_name(channel: str, sat_no: int) -> str:
    """Variable name for a meters channel scaled to kilometers."""
    return f"{channel}_km__s{sat_no}"


# --------------------------------------------------------------- variables


def _asset_channel_variable(
    channel: str,
    asset_rid: str,
    sat_no: int,
    scope: str = DATA_SCOPE_NAME,
    kind: str = "numeric",
    scale: float | None = None,
    variable_name: str | None = None,
) -> scout_channelvariables_api.ChannelVariable:
    """A variable pinned to one asset's data scope.

    assetRid is a variable named by the asset rid (same convention as
    RunChannel runRid in the ascent workbook) — the compute context resolves
    it; a bare literal is not resolved by the frontend.

    kind: "numeric" for telemetry, "log" for string log channels.
    scale: optional multiplier applied to the series (e.g. 0.001 for m -> km).
    """
    lit = scout_compute_api.StringConstant
    channel_series = scout_compute_api.ChannelSeries(
        asset=scout_compute_api.AssetChannel(
            asset_rid=lit(variable=asset_rid),
            data_scope_name=lit(literal=scope),
            channel=lit(literal=channel),
            additional_tags={},
            group_by_tags=[],
            tags_to_group_by=[],
        )
    )
    if kind == "log":
        node = scout_compute_api.ComputeNode(
            log=scout_compute_api.LogSeries(channel=channel_series)
        )
    else:
        series = scout_compute_api.NumericSeries(channel=channel_series)
        if scale is not None:
            series = scout_compute_api.NumericSeries(
                scale=scout_compute_api.ScaleSeries(
                    input=series,
                    scalar=scout_compute_api.DoubleConstant(literal=float(scale)),
                )
            )
        node = scout_compute_api.ComputeNode(numeric=series)
    return scout_channelvariables_api.ChannelVariable(
        variable_name=variable_name or _var_name(channel, sat_no),
        display_name=f"{channel} — GOCE-{sat_no}",
        compute_spec=scout_channelvariables_api.ComputeSpec(v1="{}"),
        compute_spec_v2=scout_channelvariables_api.ComputeNodeWithContext(
            compute_node=node,
            context=scout_channelvariables_api.WorkbookContext(variables={}),
        ),
    )


# ------------------------------------------------------------------ charts


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


def _markdown_chart(content: str, title: str) -> scout_chartdefinition_api.VizDefinition:
    return scout_chartdefinition_api.VizDefinition(
        markdown=scout_chartdefinition_api.MarkdownPanelDefinition(
            v1=scout_chartdefinition_api.MarkdownPanelDefinitionV1(content=content, title=title)
        )
    )


def _fleet_time_series(
    channel: str, num_sats: int, title: str
) -> scout_chartdefinition_api.VizDefinition:
    """One time-series chart, one plot per satellite."""
    axis_id = str(uuid.uuid4())
    return scout_chartdefinition_api.VizDefinition(
        time_series=scout_chartdefinition_api.TimeSeriesChartDefinition(
            v1=scout_chartdefinition_api.TimeSeriesChartDefinitionV1(
                title=title,
                comparison_run_groups=[],
                value_axes=[_value_axis(axis_id, title)],
                thresholds=[],
                rows=[
                    scout_chartdefinition_api.TimeSeriesRow(
                        row_flex_size=1.0,
                        plots=[],
                        plots_v2=[
                            scout_chartdefinition_api.TimeSeriesPlotV2(
                                variable_name=_var_name(channel, n),
                                y_axis_id=axis_id,
                                enabled=True,
                                type=scout_chartdefinition_api.TimeSeriesPlotConfig(
                                    numeric=scout_chartdefinition_api.TimeSeriesNumericPlot(
                                        color=sat_color(n),
                                        line_style=scout_chartdefinition_api.LineStyle(
                                            v1=scout_chartdefinition_api.LineStyleV1.SOLID
                                        ),
                                    )
                                ),
                            )
                            for n in range(1, num_sats + 1)
                        ],
                    )
                ],
            )
        )
    )


def _earth_view_chart(sat_nos: list[int], title: str) -> scout_chartdefinition_api.VizDefinition:
    """Geo map: one live ground track per satellite."""
    cd = scout_chartdefinition_api
    return cd.VizDefinition(
        geo=cd.GeoVizDefinition(
            v1=cd.GeoVizDefinitionV1(
                title=title,
                custom_features=[],
                base_tileset=cd.GeoBaseTileset.SATELLITE,
                unit_system=cd.GeoUnitSystem.METRIC,
                plots=[
                    cd.GeoPlotFromLatLong(
                        id=str(uuid.uuid4()),
                        label=f"GOCE-{n}",
                        enabled=True,
                        latitude_variable_name=_var_name(GEO_LAT_CHANNEL, n),
                        longitude_variable_name=_var_name(GEO_LON_CHANNEL, n),
                        visualization_options=cd.GeoPlotVisualizationOptions(
                            color=sat_color(n),
                            line_style=cd.GeoLineStyle.SOLID,
                        ),
                    )
                    for n in sat_nos
                ],
            )
        )
    )


def _earth_3d_chart(
    sat_nos: list[int], title: str, crs: str = "ecef", position: str = "wgs84"
) -> scout_chartdefinition_api.VizDefinition:
    """3D view: one orbit trail per satellite.

    position="wgs84" (default) drives the plot from the same latitude /
    longitude / altitude channels as the 2D earth view, so the two panels
    agree on where every satellite is. position="ecef" uses the km-scaled
    SST03263/64/65 replay channels instead — but note those are a *different
    orbit* (the raw GOCE replay + phase shift) than the synthetic ground-track
    model behind the geo channels, so the 2D and 3D views will disagree.

    crs="local" renders a local cartesian frame (no globe); crs="ecef"
    renders the earth-fixed globe frame. Orientation variables are left empty
    (no attitude channels in the replay) so the model flies unrotated.
    """
    cd = scout_chartdefinition_api

    def _position(n: int) -> cd.Geo3dPosition:
        if position == "wgs84":
            return cd.Geo3dPosition(
                wgs84=cd.Geo3dPositionWgs84(
                    latitude_variable_name=_var_name(GEO_LAT_CHANNEL, n),
                    longitude_variable_name=_var_name(GEO_LON_CHANNEL, n),
                    height_variable_name=_var_name(GEO_ALT_CHANNEL, n),
                )
            )
        x = _km_var_name("gnc.orbit.ecef_x_m", n)
        y = _km_var_name("gnc.orbit.ecef_y_m", n)
        z = _km_var_name("gnc.orbit.ecef_z_m", n)
        if crs == "local":
            return cd.Geo3dPosition(
                local=cd.Geo3dPositionLocal(
                    x_variable_name=x, y_variable_name=y, z_variable_name=z
                )
            )
        return cd.Geo3dPosition(
            ecef=cd.Geo3dPositionEcef(
                ecef_x_variable_name=x, ecef_y_variable_name=y, ecef_z_variable_name=z
            )
        )

    return cd.VizDefinition(
        geo3d=cd.Geo3dDefinition(
            v1=cd.Geo3dDefinitionV1(
                title=title,
                crs=(
                    cd.Geo3dCrs(local=cd.Geo3dCrsCartesian())
                    if crs == "local"
                    else cd.Geo3dCrs(ecef=cd.Geo3dCrsEcef())
                ),
                plots=[
                    cd.GeoPlot3d(
                        plot_id=str(uuid.uuid4()),
                        label=f"GOCE-{n}",
                        enabled=True,
                        position=_position(n),
                        orientation=cd.Geo3dOrientation(
                            principal_axes=cd.Geo3dOrientationPrincipalAxes(
                                heading_variable_name="",
                                pitch_variable_name="",
                                roll_variable_name="",
                            )
                        ),
                        visualization_options=cd.GeoPlot3dVisualizationOptions(
                            color=sat_color(n),
                            line_style=cd.GeoLine3dStyle.SOLID,
                            model=cd.Geo3dModel(default=cd.Geo3dDefaultModel.SATELLITE),
                        ),
                    )
                    for n in sat_nos
                ],
            )
        )
    )


CHANNEL_PALETTE = [
    "#4C79A8", "#F28E2B", "#E45756", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7",
]


def _single_sat_time_series(
    channels: list[str], sat_no: int, title: str
) -> scout_chartdefinition_api.VizDefinition:
    """One chart, several channels of the same satellite on a shared axis."""
    axis_id = str(uuid.uuid4())
    return scout_chartdefinition_api.VizDefinition(
        time_series=scout_chartdefinition_api.TimeSeriesChartDefinition(
            v1=scout_chartdefinition_api.TimeSeriesChartDefinitionV1(
                title=title,
                comparison_run_groups=[],
                value_axes=[_value_axis(axis_id, title)],
                thresholds=[],
                rows=[
                    scout_chartdefinition_api.TimeSeriesRow(
                        row_flex_size=1.0,
                        plots=[],
                        plots_v2=[
                            scout_chartdefinition_api.TimeSeriesPlotV2(
                                variable_name=_var_name(ch, sat_no),
                                y_axis_id=axis_id,
                                enabled=True,
                                type=scout_chartdefinition_api.TimeSeriesPlotConfig(
                                    numeric=scout_chartdefinition_api.TimeSeriesNumericPlot(
                                        color=CHANNEL_PALETTE[i % len(CHANNEL_PALETTE)],
                                        line_style=scout_chartdefinition_api.LineStyle(
                                            v1=scout_chartdefinition_api.LineStyleV1.SOLID
                                        ),
                                    )
                                ),
                            )
                            for i, ch in enumerate(channels)
                        ],
                    )
                ],
            )
        )
    )


# Value-table color thresholds now live in goce_limits.CHANNEL_THRESHOLDS
# (imported above): named color tokens ("green"/"yellow"/"red"), ascending
# at-or-above bands, retuned against the actual replay envelope.


def _value_table(
    entries: list[tuple[str, int]],
    title: str,
    columns: int = 2,
    row_headers: list[str] | None = None,
    col_headers: list[str] | None = None,
) -> scout_chartdefinition_api.VizDefinition:
    """Latest-value readout grid with per-cell color thresholds.

    entries: (channel, sat_no) pairs; color bands come from
    CHANNEL_THRESHOLDS (channels without an entry render uncolored).
    row_headers/col_headers annotate the grid (e.g. asset names on rows)
    via ValueTableGridRowColumnConfig(header=...).
    """
    cd = scout_chartdefinition_api
    cells = []
    for i, (ch, n) in enumerate(entries):
        bands = CHANNEL_THRESHOLDS.get(ch)
        cells.append(
            cd.ValueTableGridValueTableCell(
                row=i // columns,
                column=i % columns,
                cell=cd.ValueTableCell(
                    variable_name=_var_name(ch, n),
                    uuid=str(uuid.uuid4()),
                    config=cd.ValueTableCellConfig(
                        numeric=cd.NumericCellConfig(
                            number_format=cd.NumberFormat(sig_figs=5),
                            visualisation=cd.NumericValueVisualisationV2(
                                raw=cd.NumericRawVisualisationV2(
                                    thresholds=(
                                        [
                                            cd.Threshold(value=float(v), color=c, label=lbl)
                                            for v, c, lbl in bands
                                        ]
                                        if bands
                                        else None
                                    )
                                )
                            ),
                        )
                    ),
                ),
            )
        )
    rows = (len(entries) + columns - 1) // columns
    row_configs = (
        [cd.ValueTableGridRowColumnConfig(position=i, header=h) for i, h in enumerate(row_headers)]
        if row_headers
        else []
    )
    column_configs = (
        [cd.ValueTableGridRowColumnConfig(position=i, header=h) for i, h in enumerate(col_headers)]
        if col_headers
        else []
    )
    return cd.VizDefinition(
        value_table=cd.ValueTableDefinition(
            v2=cd.ValueTableDefinitionV2(
                title=title,
                show_units=True,
                # Cell labels off when headers carry the annotation —
                # the label otherwise crops the asset name at table
                # aspect ratios.
                show_staleness_indicator=False,
                staleness_indicator=cd.ValueTableStalenessConfig(hide_staleness=True),
                layout=cd.ValueTableLayout(
                    grid=cd.ValueTableLayoutGrid(
                        row_count=rows,
                        column_count=columns,
                        show_cell_labels=not (row_headers or col_headers),
                        # Headers only render when explicitly enabled
                        # (galaxy: panel.showRowHeaders ?? false).
                        show_row_headers=bool(row_headers),
                        show_column_headers=bool(col_headers),
                        row_header_width=120.0 if row_headers else None,
                        grid_default_cell_configs=cd.ValueTableMultiCellConfig(),
                        column_configs=column_configs,
                        row_configs=row_configs,
                        cells=cells,
                    )
                ),
            )
        )
    )


def _fleet_scatter(
    x_channel: str, y_channel: str, sat_nos: list[int], title: str, connect: bool = True
) -> scout_chartdefinition_api.VizDefinition:
    """Cartesian scatter, one plot per satellite (e.g. ECEF X vs Y —
    the constellation's orbital ring seen pole-on)."""
    cd = scout_chartdefinition_api
    x_axis, y_axis = str(uuid.uuid4()), str(uuid.uuid4())
    return cd.VizDefinition(
        cartesian=cd.CartesianChartDefinition(
            v1=cd.CartesianChartDefinitionV1(
                title=title,
                comparison_run_groups=[],
                connect_points=connect,
                value_axes=[_value_axis(x_axis, x_channel), _value_axis(y_axis, y_channel)],
                plots=[
                    cd.CartesianPlot(
                        color=sat_color(n),
                        x_axis_id=x_axis,
                        x_variable_name=_var_name(x_channel, n),
                        y_axis_id=y_axis,
                        y_variable_name=_var_name(y_channel, n),
                        enabled=True,
                    )
                    for n in sat_nos
                ],
            )
        )
    )


def _fleet_histogram(
    channel: str, sat_nos: list[int], title: str
) -> scout_chartdefinition_api.VizDefinition:
    """Distribution bar chart, one series per satellite — dispersion of
    the fleet at a glance (outlier bars pop immediately)."""
    cd = scout_chartdefinition_api
    return cd.VizDefinition(
        histogram=cd.HistogramChartDefinition(
            v1=cd.HistogramChartDefinitionV1(
                title=title,
                display_settings=cd.HistogramDisplaySettings(
                    sort=cd.HistogramSortOrder.VALUE_ASCENDING, stacked=False
                ),
                plots=[
                    cd.HistogramPlot(
                        variable_name=_var_name(channel, n), color=sat_color(n), enabled=True
                    )
                    for n in sat_nos
                ],
            )
        )
    )


def _checklist_panel(title: str) -> scout_chartdefinition_api.VizDefinition:
    """Embedded live checklist panel (bus-health limits).

    NOTE: renders "Something went wrong" in the demo tenant as of
    2026-08-12 (likely gated by the checklistReportView flag, which is
    constrained to a different org) — not used in layouts until it
    renders; kept for when the flag ships.
    """
    cd = scout_chartdefinition_api
    return cd.VizDefinition(
        checklist=cd.ChecklistChartDefinition(
            v1=cd.ChecklistChartDefinitionV1(
                title=title, selected_checklist_rids=[CHECKLIST_RID]
            )
        )
    )


def _log_panel(channel: str, sat_no: int, title: str) -> scout_chartdefinition_api.VizDefinition:
    cd = scout_chartdefinition_api
    return cd.VizDefinition(
        log=cd.LogPanelDefinition(
            v1=cd.LogPanelDefinitionV1(
                title=title,
                log_channels=[],
                log_channels_v2=[
                    cd.LogChannel(
                        log_channel_variable_name=_var_name(channel, sat_no),
                        visible_log_column_names=[],
                        tag_filters={},
                    )
                ],
            )
        )
    )


# ------------------------------------------------------------------ layout
# All tabs are CANVAS layouts (free-placed panels, pixel rects on a
# ~1600-wide grid) — the frontend's default and the only layout that
# supports the dense, asymmetric arrangements the demo needs.


def _canvas_tab(
    title: str, placed: list[tuple[str, float, float, float, float]]
) -> scout_layout_api.SingleTab:
    """placed: (chart_id, x, y, w, h) in canvas pixels (~1600-wide grid)."""
    return scout_layout_api.SingleTab(
        v1=scout_layout_api.SingleTabV1(
            title=title,
            panel=scout_layout_api.Panel(
                canvas=scout_layout_api.CanvasLayout(
                    id=str(uuid.uuid4()),
                    objects={
                        chart_id: scout_layout_api.CanvasObject(
                            panel=scout_layout_api.CanvasPanel(
                                rect=scout_layout_api.CanvasRect(x=x, y=y, width=w, height=h),
                                hide_legend=False,
                            )
                        )
                        for chart_id, x, y, w, h in placed
                    },
                )
            ),
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


# ----------------------------------------------------------------- content


def _workbook_content(asset_rids: list[str]):
    """Returns (content_v2, layout) for the constellation workbook.

    Every tab is a canvas with a dense, asymmetric mix of panel types:
    hero panels + supporting readouts, not uniform 2x2 grids.
    """
    num_sats = len(asset_rids)

    fleet_channels = (
        [GEO_LAT_CHANNEL, GEO_LON_CHANNEL, GEO_ALT_CHANNEL]
        + [c for c, _ in ORBIT_CHANNELS]
        + [c for c, _ in THERMAL_CHANNELS]
        + [c for c, _ in POWER_CHANNELS]
        + [PAYLOAD_CURRENT]
    )
    channel_variables = {
        _var_name(ch, n): _asset_channel_variable(ch, rid, n)
        for ch in fleet_channels
        for n, rid in enumerate(asset_rids, start=1)
    }
    # km-scaled ECEF variables for the 3D earth view (renderer expects km)
    channel_variables.update(
        {
            _km_var_name(ch, n): _asset_channel_variable(
                ch, rid, n, scale=0.001, variable_name=_km_var_name(ch, n)
            )
            for ch, _ in ORBIT_CHANNELS
            for n, rid in enumerate(asset_rids, start=1)
        }
    )
    # Live spacecraft log for the fault satellite (GOCE-7), shown on the
    # Fleet status tab next to the health grid.
    log_sat = 7 if num_sats >= 7 else 1
    channel_variables[_var_name(LOG_CHANNEL, log_sat)] = _asset_channel_variable(
        LOG_CHANNEL, asset_rids[log_sat - 1], log_sat, kind="log"
    )

    charts: dict[str, scout_chartdefinition_api.VizDefinition] = {}

    def add(viz: scout_chartdefinition_api.VizDefinition) -> str:
        viz_id = str(uuid.uuid4())
        charts[viz_id] = viz
        return viz_id

    sat_nos = list(range(1, num_sats + 1))
    W = 1600.0

    # ------------------------------------------------------- Overview
    overview_md = add(_markdown_chart(OVERVIEW_MARKDOWN, "Constellation overview"))
    ov_geo = add(_earth_view_chart(sat_nos, "Constellation earth view"))
    ov_ref_table = add(
        _value_table(
            [(ch, n) for n in (1, 7 if num_sats >= 7 else 1) for ch in FLEET_STATUS_CHANNELS],
            "Reference vs GOCE-7",
            columns=len(FLEET_STATUS_CHANNELS),
            row_headers=["GOCE-1 (ref)", f"GOCE-{7 if num_sats >= 7 else 1}"],
            col_headers=FLEET_STATUS_HEADERS,
        )
    )
    ov_duty = add(_fleet_time_series(HTR_CHANNEL, num_sats, "HTR-2 heater duty [%] — fleet"))
    ov_current = add(_fleet_time_series(BUS_CURRENT, num_sats, "Main bus current [A] — fleet"))

    # --------------------------------------------------- Fleet status
    # One row per satellite (row headers carry the asset names — cell
    # labels crop at table aspect ratios), threshold-colored columns.
    fleet_table = add(
        _value_table(
            [(ch, n) for n in sat_nos for ch in FLEET_STATUS_CHANNELS],
            "Fleet status — live limits, one row per satellite",
            columns=len(FLEET_STATUS_CHANNELS),
            row_headers=[f"GOCE-{n}" for n in sat_nos],
            col_headers=FLEET_STATUS_HEADERS,
        )
    )
    fs_voltage = add(_fleet_time_series(BUS_VOLTAGE, num_sats, "Bus voltage [V] — fleet"))
    fs_current = add(_fleet_time_series(BUS_CURRENT, num_sats, "Bus current [A] — fleet"))
    fs_duty = add(_fleet_time_series(HTR_CHANNEL, num_sats, "HTR-2 duty [%] — fleet"))
    fs_logs = add(_log_panel(LOG_CHANNEL, log_sat, f"GOCE-{log_sat} spacecraft log"))

    # ------------------------------------------------------ Earth view
    ev_geo = add(_earth_view_chart(sat_nos, "Ground tracks"))
    ev_3d = add(_earth_3d_chart(sat_nos, "Constellation 3D view"))
    ev_alt = add(_fleet_time_series(GEO_ALT_CHANNEL, num_sats, "Altitude [km]"))

    # ----------------------------------------------------------- Orbit
    orbit_scatter = add(
        _fleet_scatter(
            "gnc.orbit.ecef_x_m",
            "gnc.orbit.ecef_y_m",
            sat_nos,
            "Constellation ring — ECEF X vs Y (pole-on view)",
        )
    )
    orbit_z = add(_fleet_time_series("gnc.orbit.ecef_z_m", num_sats, "ECEF Z position [m]"))
    orbit_alt = add(_fleet_time_series(GEO_ALT_CHANNEL, num_sats, "Altitude [km]"))

    # --------------------------------------------------------- Thermal
    th_bus = add(_fleet_time_series(BUS_TEMP, num_sats, "Bus temperature [°C] — fleet"))
    th_hist = add(_fleet_histogram(BUS_TEMP, sat_nos, "Bus temp distribution by satellite"))
    th_gps = add(
        _fleet_time_series("tcs.avionics.gps_temp_c", num_sats, "GPS receiver temp [°C]")
    )
    th_xband = add(
        _fleet_time_series("tcs.avionics.xband_temp_c", num_sats, "X-band transmitter temp [°C]")
    )

    # ---------------------------------------------------- EPS & heater
    eps_duty = add(_fleet_time_series(HTR_CHANNEL, num_sats, "HTR-2 heater duty [%] — fleet"))
    eps_v = add(_fleet_time_series(BUS_VOLTAGE, num_sats, "Main bus voltage [V] — fleet"))
    eps_i = add(_fleet_time_series(BUS_CURRENT, num_sats, "Main bus current [A] — fleet"))
    eps_hist = add(_fleet_histogram(BUS_CURRENT, sat_nos, "Bus current distribution by satellite"))
    eps_payload = add(
        _fleet_time_series(PAYLOAD_CURRENT, num_sats, "Payload feed current [A] — fleet")
    )
    ref_vs_fault = add(
        _value_table(
            [(ch, n) for n in (1, log_sat) for ch in FLEET_STATUS_CHANNELS],
            "Reference vs fault satellite",
            columns=len(FLEET_STATUS_CHANNELS),
            row_headers=[f"GOCE-1 (ref)", f"GOCE-{log_sat}"],
            col_headers=FLEET_STATUS_HEADERS,
        )
    )

    layout = _tabbed_layout(
        [
            _canvas_tab(
                "Overview",
                [
                    (overview_md, 0, 0, 560, 430),
                    (ov_geo, 560, 0, 1040, 430),
                    (ov_ref_table, 0, 430, 560, 330),
                    (ov_duty, 560, 430, 520, 330),
                    (ov_current, 1080, 430, 520, 330),
                ],
            ),
            _canvas_tab(
                "Fleet status",
                [
                    (fleet_table, 0, 0, 880, 1280),
                    (fs_voltage, 880, 0, 720, 300),
                    (fs_current, 880, 300, 720, 320),
                    (fs_duty, 880, 620, 720, 320),
                    (fs_logs, 880, 940, 720, 340),
                ],
            ),
            _canvas_tab(
                "Earth view",
                [
                    (ev_geo, 0, 0, 1000, 720),
                    (ev_3d, 1000, 0, 600, 360),
                    (ev_alt, 1000, 360, 600, 360),
                ],
            ),
            _canvas_tab(
                "Orbit",
                [
                    (orbit_scatter, 0, 0, 880, 720),
                    (orbit_z, 880, 0, 720, 360),
                    (orbit_alt, 880, 360, 720, 360),
                ],
            ),
            _canvas_tab(
                "Thermal",
                [
                    (th_bus, 0, 0, W, 340),
                    (th_hist, 0, 340, 530, 340),
                    (th_gps, 530, 340, 535, 340),
                    (th_xband, 1065, 340, 535, 340),
                ],
            ),
            _canvas_tab(
                "EPS & heater",
                [
                    (eps_duty, 0, 0, W, 300),
                    (eps_v, 0, 300, 800, 330),
                    (eps_i, 800, 300, 800, 330),
                    (eps_hist, 0, 630, 530, 330),
                    (eps_payload, 530, 630, 535, 330),
                    (ref_vs_fault, 1065, 630, 535, 330),
                ],
            ),
        ]
    )
    content = scout_workbookcommon_api.WorkbookContent(
        channel_variables=channel_variables, charts=charts
    )
    return scout_workbookcommon_api.UnifiedWorkbookContent(workbook=content), layout


# ------------------------------------------------- single-satellite workbook
# Channel groups are imported from goce_channels (hierarchical namespace).

HEALTH_GLANCE_CHANNELS = [
    GEO_ALT_CHANNEL, BUS_VOLTAGE, BUS_CURRENT, BUS_TEMP,
    HTR_CHANNEL, "aocs.rw.wheel_1_speed_rpm",
]
THERMAL_GLANCE_CHANNELS = [
    BUS_TEMP, "tcs.bus.battery_temp_c", "tcs.bus.transponder_temp_c",
    "tcs.avionics.gps_temp_c", "tcs.structure.radiator_temp_c",
    "tcs.solar_panel.wing_a_inner_temp_c",
]
POWER_GLANCE_CHANNELS = [
    BUS_VOLTAGE, "eps.bus.secondary_voltage_v", BUS_CURRENT,
    PAYLOAD_CURRENT, "eps.pcdu.total_load_w", "tcs.pcdu.temp_c",
]


def single_sat_title(sat_no: int) -> str:
    return f"GOCE-{sat_no}: telemetry & bus health"


def _single_sat_markdown(sat_no: int) -> str:
    shell = (sat_no - 1) // (NUM_SATELLITES // NUM_SHELLS) + 1
    role = "the nominal reference (no dispersion)" if sat_no == 1 else (
        "a dispersed unit (per-satellite gain/drift applied to bus telemetry)"
    )
    return f"""\
# GOCE-{sat_no} — satellite zoom-down

Single-satellite deep dive for **GOCE-{sat_no}** (plane {shell} of {NUM_SHELLS}),
{role}. Same live stream as the constellation workbook, scoped to this
asset's `satellite = GOCE-{sat_no}` tag.

| Tab | Contents |
|---|---|
| Orbit | 3D earth view, ground track, altitude, ECEF position & velocity |
| Thermal | Bus, structure, and solar-panel temperatures + latest readouts |
| Power | Bus voltages, load currents, power rails + latest readouts |
| AOCS & sensors | Reaction wheels, accelerometers, magnetometers |
| Logs | Live spacecraft log stream |

Structure temps (THT) sample every ~3 s wall — widen the live window
(e.g. 5 min) to see their trends.
"""


def _single_sat_content(asset_rid: str, sat_no: int):
    """Returns (content_v2, layout) for the single-satellite workbook."""
    numeric_channels = (
        [GEO_LAT_CHANNEL, GEO_LON_CHANNEL, GEO_ALT_CHANNEL]
        + [c for c, _ in ORBIT_CHANNELS]
        + BUS_TEMP_CHANNELS
        + STRUCT_TEMP_CHANNELS
        + PANEL_TEMP_CHANNELS
        + BUS_VOLTAGE_CHANNELS
        + BUS_CURRENT_CHANNELS
        + POWER_RAIL_CHANNELS
        + WHEEL_CHANNELS
        + ACCEL_CHANNELS
        + MAG_CHANNELS
        + VELOCITY_CHANNELS
        + [HTR_CHANNEL]
    )
    channel_variables = {
        _var_name(ch, sat_no): _asset_channel_variable(ch, asset_rid, sat_no)
        for ch in numeric_channels
    }
    channel_variables[_var_name(LOG_CHANNEL, sat_no)] = _asset_channel_variable(
        LOG_CHANNEL, asset_rid, sat_no, kind="log"
    )
    # km-scaled ECEF variables for the 3D orbit view (renderer expects km)
    channel_variables.update(
        {
            _km_var_name(ch, sat_no): _asset_channel_variable(
                ch, asset_rid, sat_no, scale=0.001, variable_name=_km_var_name(ch, sat_no)
            )
            for ch, _ in ORBIT_CHANNELS
        }
    )

    charts: dict[str, scout_chartdefinition_api.VizDefinition] = {}

    def add(viz: scout_chartdefinition_api.VizDefinition) -> str:
        viz_id = str(uuid.uuid4())
        charts[viz_id] = viz
        return viz_id

    def glance(channels: list[str], title: str) -> str:
        return add(_value_table([(ch, sat_no) for ch in channels], title))

    W = 1600.0
    # Overview: markdown + health grid + checklist + track/3D pair
    ov_md = add(_markdown_chart(_single_sat_markdown(sat_no), f"GOCE-{sat_no} overview"))
    ov_health = glance(HEALTH_GLANCE_CHANNELS, "Bus health at a glance")
    ov_logs = add(_log_panel(LOG_CHANNEL, sat_no, "Live spacecraft log"))
    ov_ground = add(_earth_view_chart([sat_no], f"GOCE-{sat_no} ground track"))
    ov_3d = add(_earth_3d_chart([sat_no], f"GOCE-{sat_no} 3D orbit"))

    # Orbit: 3D + ground + ECEF ring scatter + velocity
    or_3d = add(_earth_3d_chart([sat_no], "3D orbit"))
    or_ground = add(_earth_view_chart([sat_no], "Ground track"))
    or_scatter = add(
        _fleet_scatter(
            "gnc.orbit.ecef_x_m", "gnc.orbit.ecef_y_m", [sat_no], "Orbit ring — ECEF X vs Y"
        )
    )
    or_alt = add(_single_sat_time_series([GEO_ALT_CHANNEL], sat_no, "Altitude [km]"))
    or_vel = add(_single_sat_time_series(VELOCITY_CHANNELS, sat_no, "ECEF velocity [m/s]"))

    # Thermal: hero bus temps + structure/panel + distribution + glance
    th_bus = add(_single_sat_time_series(BUS_TEMP_CHANNELS, sat_no, "Bus temperatures [°C]"))
    th_struct = add(_single_sat_time_series(STRUCT_TEMP_CHANNELS, sat_no, "Structure temperatures [°C]"))
    th_panel = add(_single_sat_time_series(PANEL_TEMP_CHANNELS, sat_no, "Solar panel temperatures [°C]"))
    th_hist = add(_fleet_histogram(BUS_TEMP_CHANNELS[0], [sat_no], "Bus temp distribution"))
    th_glance = glance(THERMAL_GLANCE_CHANNELS, "Latest temperatures")

    # Power: voltages/currents + rails + distribution + glance
    pw_v = add(_single_sat_time_series(BUS_VOLTAGE_CHANNELS, sat_no, "Bus voltages [V]"))
    pw_i = add(_single_sat_time_series(BUS_CURRENT_CHANNELS, sat_no, "Load currents [A]"))
    pw_rails = add(_single_sat_time_series(POWER_RAIL_CHANNELS, sat_no, "Power rails"))
    pw_hist = add(_fleet_histogram(BUS_CURRENT_CHANNELS[0], [sat_no], "Bus current distribution"))
    pw_glance = glance(POWER_GLANCE_CHANNELS, "Latest EPS readouts")

    # AOCS & sensors: wheels hero + gradiometer + mag + lat/lon scatter
    ao_wheels = add(_single_sat_time_series(WHEEL_CHANNELS, sat_no, "Reaction wheel speeds [rpm]"))
    ao_grad = add(_single_sat_time_series(ACCEL_CHANNELS, sat_no, "Gradiometer [m/s²]"))
    ao_mag = add(_single_sat_time_series(MAG_CHANNELS, sat_no, "Magnetometers [nT]"))
    ao_track = add(
        _fleet_scatter(GEO_LON_CHANNEL, GEO_LAT_CHANNEL, [sat_no], "Ground track — lon vs lat")
    )

    # Logs: hero log panel + duty + wheels context
    lg_logs = add(_log_panel(LOG_CHANNEL, sat_no, f"GOCE-{sat_no} spacecraft logs"))
    lg_duty = add(_single_sat_time_series([HTR_CHANNEL], sat_no, "HTR-2 heater duty [%]"))
    lg_wheels = add(_single_sat_time_series(WHEEL_CHANNELS, sat_no, "Wheel speeds (context)"))

    layout = _tabbed_layout(
        [
            _canvas_tab(
                "Overview",
                [
                    (ov_md, 0, 0, 520, 380),
                    (ov_health, 520, 0, 560, 380),
                    (ov_logs, 1080, 0, 520, 380),
                    (ov_ground, 0, 380, 800, 420),
                    (ov_3d, 800, 380, 800, 420),
                ],
            ),
            _canvas_tab(
                "Orbit",
                [
                    (or_3d, 0, 0, 800, 460),
                    (or_ground, 800, 0, 800, 460),
                    (or_scatter, 0, 460, 620, 360),
                    (or_alt, 620, 460, 490, 360),
                    (or_vel, 1110, 460, 490, 360),
                ],
            ),
            _canvas_tab(
                "Thermal",
                [
                    (th_glance, 0, 0, W, 200),
                    (th_bus, 0, 200, 1060, 340),
                    (th_hist, 1060, 200, 540, 340),
                    (th_struct, 0, 540, 800, 330),
                    (th_panel, 800, 540, 800, 330),
                ],
            ),
            _canvas_tab(
                "Power",
                [
                    (pw_glance, 0, 0, W, 200),
                    (pw_v, 0, 200, 800, 330),
                    (pw_i, 800, 200, 800, 330),
                    (pw_rails, 0, 530, 1060, 330),
                    (pw_hist, 1060, 530, 540, 330),
                ],
            ),
            _canvas_tab(
                "AOCS & sensors",
                [
                    (ao_wheels, 0, 0, W, 320),
                    (ao_grad, 0, 320, 530, 340),
                    (ao_mag, 530, 320, 535, 340),
                    (ao_track, 1065, 320, 535, 340),
                ],
            ),
            _canvas_tab(
                "Logs",
                [
                    (lg_logs, 0, 0, 1000, 660),
                    (lg_duty, 1000, 0, 600, 330),
                    (lg_wheels, 1000, 330, 600, 330),
                ],
            ),
        ]
    )
    content = scout_workbookcommon_api.WorkbookContent(
        channel_variables=channel_variables, charts=charts
    )
    return scout_workbookcommon_api.UnifiedWorkbookContent(workbook=content), layout


TEMPLATE_TITLE = "GOCE satellite zoom-down"


def upsert_template(client: NominalClient, asset_rid: str, sat_no: int):
    """Publish the single-satellite dashboard as a Nominal workbook template.

    The template carries the same content as the GOCE-N workbook. Channel
    variables are pinned to the source asset's rid (as a variable name the
    compute context resolves); when applying the template to a different
    asset in the app, verify the plots rebind to the new data scope.
    """
    from nominal_api import scout_template_api as st

    auth = client._clients.auth_header
    content_v2, layout = _single_sat_content(asset_rid, sat_no)
    content = content_v2.workbook

    existing_rid = None
    try:
        resp = client._clients.template.search_templates(
            auth,
            st.SearchTemplatesRequest(
                query=st.SearchTemplatesQuery(exact_match=TEMPLATE_TITLE)
            ),
        )
        for tpl in getattr(resp, "results", []) or []:
            meta = getattr(tpl, "metadata", tpl)
            if getattr(meta, "title", None) == TEMPLATE_TITLE:
                existing_rid = getattr(meta, "rid", None) or getattr(tpl, "rid", None)
                break
    except Exception as e:
        print(f"Template search failed ({e}); will create a new template")

    if existing_rid is None:
        request = st.CreateTemplateRequest(
            title=TEMPLATE_TITLE,
            description=(
                "Single-satellite telemetry & bus health dashboard for a GOCE "
                "asset: orbit (3D + ground track), thermal, power, AOCS "
                "sensors, live logs, and color-thresholded health readouts."
            ),
            labels=["GOCE"],
            properties={"source": "constellation_workbook.py"},
            is_published=True,
            layout=layout,
            content=content,
            message="Initial version",
            workspace=client._clients.resolve_default_workspace_rid(),
        )
        tpl = client._clients.template.create(auth, request)
        rid = getattr(tpl, "rid", None) or getattr(getattr(tpl, "metadata", None), "rid", None)
        print(f"Created template: {TEMPLATE_TITLE} ({rid})")
        return rid

    tpl = client._clients.template.get(auth, existing_rid)
    latest_commit = getattr(getattr(tpl, "commit", None), "id", None)
    client._clients.template.commit(
        auth,
        st.CommitTemplateRequest(
            layout=layout,
            content=content,
            message="Converge from constellation_workbook.py",
            latest_commit=latest_commit,
        ),
        existing_rid,
    )
    print(f"Updated template in place: {TEMPLATE_TITLE} ({existing_rid})")
    return existing_rid


# ------------------------------------------------------------------ driver


def find_assets(client: NominalClient, num_sats: int) -> list:
    assets = []
    for n in range(1, num_sats + 1):
        name = f"GOCE-{n}"
        found = client.search_assets(search_text=name, properties={"asset_id": name})
        asset = next((a for a in found if a.name == name), None)
        if asset is None:
            raise SystemExit(
                f"Asset not found: {name} — start goce_csv_streamer.py with "
                f"--num-satellites {num_sats} first (assets are created ~2s after launch)"
            )
        assets.append(asset)
    return assets


def upsert_workbook(
    client: NominalClient, title: str, asset_rids: list[str], content_v2, layout, description: str
):
    """Create the workbook, or converge an existing one's content and layout."""
    existing = None
    for wb in client.search_workbooks(exact_match=title):
        if wb.title == title:
            existing = wb
            break

    if existing is None:
        request = scout_notebook_api.CreateNotebookRequest(
            title=title,
            description=description,
            notebook_type=None,
            is_draft=False,
            state_as_json="{}",
            data_scope=scout_notebook_api.NotebookDataScope(asset_rids=list(asset_rids)),
            layout=layout,
            content_v2=content_v2,
            event_refs=[],
            workspace=client._clients.resolve_default_workspace_rid(),
        )
        raw = client._clients.notebook.create(client._clients.auth_header, request)
        wb = client.get_workbook(raw.rid)
        print(f"Created workbook: {title} ({wb.rid})")
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
    print(f"Updated workbook in place: {title} ({existing.rid})")
    return existing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--num-satellites", type=int, default=NUM_SATELLITES)
    parser.add_argument(
        "--satellite",
        type=int,
        default=1,
        help="Satellite number for the single-sat zoom-down workbook (default: 1)",
    )
    args = parser.parse_args()

    client = NominalClient.from_profile(args.profile)
    user = client.get_user()
    print(f"Authenticated as: {user.display_name} ({user.email})")

    assets = find_assets(client, args.num_satellites)
    print(f"Found {len(assets)} assets (GOCE-1 … GOCE-{args.num_satellites})")
    asset_rids = [a.rid for a in assets]

    content_v2, layout = _workbook_content(asset_rids)
    constellation = upsert_workbook(
        client,
        WORKBOOK_TITLE,
        asset_rids,
        content_v2,
        layout,
        f"Live fleet view of the {len(asset_rids)}-satellite GOCE constellation: "
        "earth view ground tracks, 3D orbits, phase spread, thermal and power overlays.",
    )

    sat_no = args.satellite
    sat_rid = asset_rids[sat_no - 1]
    sc_content, sc_layout = _single_sat_content(sat_rid, sat_no)
    single = upsert_workbook(
        client,
        single_sat_title(sat_no),
        [sat_rid],
        sc_content,
        sc_layout,
        f"Single-satellite zoom-down for GOCE-{sat_no}: orbit, thermal, power, "
        "AOCS sensors, and live spacecraft logs.",
    )

    template_rid = upsert_template(client, sat_rid, sat_no)

    print("\n=== URLs ===")
    print(f"Constellation workbook: {constellation.nominal_url}")
    print(f"GOCE-{sat_no} zoom-down:  {single.nominal_url}")
    print(f"Template rid:           {template_rid}")


if __name__ == "__main__":
    main()
