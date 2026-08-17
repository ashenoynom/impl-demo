#!/usr/bin/env python3
"""First-class GOCE single-satellite workbook + bus-health checklist.

Built per the nominal-builder skill (verified against nominal-api 0.1373):

- Workbook "GOCE-N: bus health deep-dive": canvas layout (tabs of freely
  placed panels, pixel rects on a 1600-wide grid, mirroring the ISS Dashboard
  reference workbook), a first-class *data scope input* so the satellite is
  swappable from the workbook's input picker, redline thresholds drawn on the
  charts, value-table KPI strips, histograms, geo/geo3d, and live logs.
- Checklist "GOCE satellite bus health limits": threshold / band / sustained /
  any-of checks over the bus channels, run/asset-agnostic via ChannelLocator
  ref name "data".

Reference-verified contracts:
- dataScopeInputs.v1.inputs is a Dict keyed by the input variable name; the
  UI keys it by the asset rid and compute nodes reference that key (the ISS
  Dashboard binds e.g. reference(name=<asset rid>)). Channel variables here
  use AssetChannel(asset_rid=StringConstant(variable=<input key>)).
- CanvasLayout.objects keys ARE chart ids; rects are pixels (~1600 wide).

Usage:
    python goce_deepdive_builder.py [--profile goce_streamer] [--satellite 1]
"""

from __future__ import annotations

import argparse
import uuid

from nominal.core import NominalClient
from nominal_api import (
    scout_api,
    scout_channelvariables_api,
    scout_chartdefinition_api,
    scout_checks_api,
    scout_compute_api,
    scout_layout_api,
    scout_notebook_api,
    scout_run_api,
    scout_workbookcommon_api,
)

from constellation_workbook import (
    CHANNEL_PALETTE,
    HEALTH_GLANCE_CHANNELS,
    NUM_SHELLS,
    ORBIT_CHANNELS,
    POWER_GLANCE_CHANNELS,
    THERMAL_GLANCE_CHANNELS,
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
    GROUND_STATIONS,
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
from goce_limits import (
    CHANNEL_THRESHOLDS,
    HEX_ALARM,
    HEX_WARN,
    KELVIN_OFFSET_C,
    RADIATOR_AREA_M2,
    RADIATOR_EMISSIVITY,
    RADIATOR_SIGMA_EPS_A,
    STEFAN_BOLTZMANN_W_M2K4,
    LIMIT_ALT_BOX_HIGH_KM,
    LIMIT_ALT_BOX_LOW_KM,
    LIMIT_BUS_OVERCURRENT_A,
    LIMIT_BUS_POWER_BUDGET_W,
    LIMIT_BUS_TEMP_HOT_C,
    LIMIT_BUS_UNDERVOLT_V,
    LIMIT_HTR_DUTY_LATCHED_PCT,
    LIMIT_PANEL_SUSTAINED_C,
    LIMIT_PAYLOAD_OVERCURRENT_A,
    LIMIT_RADIATOR_WARM_C,
    LIMIT_WHEEL_SATURATION_RPM,
)

DATA_SCOPE_NAME = "data"
WORKBOOK_TITLE = "GOCE-{n}: bus health deep-dive"
CHECKLIST_TITLE = "GOCE satellite bus health limits"
PROCEDURE_RID = "ri.scout.cerulean-staging.procedure.f789cd49-0e68-4d23-b37f-e8d162413c15"

# The live-built UDFs: main bus power from first principles (P = V x I),
# then the Stefan-Boltzmann radiator equilibrium prediction built on it.
BUS_POWER_VAR = "eps.bus.power_w"
RADIATOR_EQ_VAR = "tcs.radiator.predicted_eq_temp_c"
MEASURED_RADIATOR = "tcs.structure.radiator_temp_c"

cd = scout_chartdefinition_api
sc = scout_compute_api
sl = scout_layout_api
wc = scout_workbookcommon_api


# ------------------------------------------------------------- variables


def _channel_variable(channel: str, input_key: str, kind: str = "numeric"):
    """Bind a channel from the satellite data scope input into a variable.

    input_key is the data scope input's dict key (the asset rid, mirroring
    the ISS Dashboard reference); the compute context resolves it.
    """
    lit = sc.StringConstant
    series = sc.ChannelSeries(
        asset=sc.AssetChannel(
            asset_rid=lit(variable=input_key),
            data_scope_name=lit(literal=DATA_SCOPE_NAME),
            channel=lit(literal=channel),
            additional_tags={},
            group_by_tags=[],
            tags_to_group_by=[],
        )
    )
    if kind == "log":
        node = sc.ComputeNode(log=sc.LogSeries(channel=series))
    else:
        node = sc.ComputeNode(numeric=sc.NumericSeries(channel=series))
    return scout_channelvariables_api.ChannelVariable(
        variable_name=channel,
        display_name=channel,
        compute_spec=scout_channelvariables_api.ComputeSpec(v1="{}"),
        compute_spec_v2=scout_channelvariables_api.ComputeNodeWithContext(
            compute_node=node,
            context=scout_channelvariables_api.WorkbookContext(variables={}),
        ),
    )


def _asset_numeric_series(channel: str, input_key: str) -> sc.NumericSeries:
    lit = sc.StringConstant
    return sc.NumericSeries(
        channel=sc.ChannelSeries(
            asset=sc.AssetChannel(
                asset_rid=lit(variable=input_key),
                data_scope_name=lit(literal=DATA_SCOPE_NAME),
                channel=lit(literal=channel),
                additional_tags={},
                group_by_tags=[],
                tags_to_group_by=[],
            )
        )
    )


def _bus_power_variable(input_key: str):
    """The demo UDF, pre-staged: eps.bus.power_w = bus voltage x bus
    current. In the demo this is also live-built from first principles
    in the workbook UI; this variable is the saved end state.

    NOTE: uses ProductSeries, not Multiply — the galaxy frontend's
    compute deserializer throws on raw binary nodes (multiply/add/
    divide/power/sqrt); only product/arithmetic/binaryArithmetic/
    unaryArithmetic/scale/offset render."""
    node = sc.ComputeNode(
        numeric=sc.NumericSeries(
            product=sc.ProductSeries(
                inputs=[
                    _asset_numeric_series(BUS_VOLTAGE, input_key),
                    _asset_numeric_series(BUS_CURRENT, input_key),
                ]
            )
        )
    )
    return scout_channelvariables_api.ChannelVariable(
        variable_name=BUS_POWER_VAR,
        display_name=f"{BUS_POWER_VAR} (V x I)",
        compute_spec=scout_channelvariables_api.ComputeSpec(v1="{}"),
        compute_spec_v2=scout_channelvariables_api.ComputeNodeWithContext(
            compute_node=node,
            context=scout_channelvariables_api.WorkbookContext(variables={}),
        ),
    )


def _radiator_eq_variable(input_key: str):
    """Stefan-Boltzmann radiator equilibrium prediction:

        T_eq = (P / (epsilon * sigma * A))^(1/4) - 273.15   [degC]

    built as a single ArithmeticSeries formula (the frontend's formula
    editor node — the only frontend-renderable way to express the
    fourth root; galaxy's deserializer throws on raw sqrt/multiply/
    power nodes and its unaryArithmetic case has no SQRT):

        sqrt(sqrt((volts * amps) * K)) - 273.15,  K = 1/(eps*sigma*A)
    """
    inv_sea = 1.0 / RADIATOR_SIGMA_EPS_A  # ~4.26e8; format as plain int
    expression = f"sqrt(sqrt((volts * amps) * {inv_sea:.0f})) - {-KELVIN_OFFSET_C}"
    node = sc.ComputeNode(
        numeric=sc.NumericSeries(
            arithmetic=sc.ArithmeticSeries(
                expression=expression,
                inputs={
                    "volts": _asset_numeric_series(BUS_VOLTAGE, input_key),
                    "amps": _asset_numeric_series(BUS_CURRENT, input_key),
                },
            )
        )
    )
    return scout_channelvariables_api.ChannelVariable(
        variable_name=RADIATOR_EQ_VAR,
        display_name=f"{RADIATOR_EQ_VAR} (Stefan-Boltzmann)",
        compute_spec=scout_channelvariables_api.ComputeSpec(v1="{}"),
        compute_spec_v2=scout_channelvariables_api.ComputeNodeWithContext(
            compute_node=node,
            context=scout_channelvariables_api.WorkbookContext(variables={}),
        ),
    )


# ---------------------------------------------------------------- charts


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
    """lines: (value, label, color, solid) — redlines drawn on the chart."""
    return cd.AxisThresholdVisualization(
        axis_id=axis_id,
        visibility=True,
        thresholds=cd.AxisThresholdGroup(
            line_thresholds=cd.LineThresholdGroup(
                lines=[
                    cd.LineThreshold(
                        value=value,
                        label=label,
                        color=color,
                        line_style=(
                            cd.ThresholdLineStyle.SOLID if solid else cd.ThresholdLineStyle.DOTTED
                        ),
                    )
                    for value, label, color, solid in lines
                ],
                shading_config=cd.ThresholdShadingConfig.NONE,
            )
        ),
    )


def _time_series(
    channels: list[str],
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
                                variable_name=ch,
                                y_axis_id=axis_id,
                                enabled=True,
                                type=cd.TimeSeriesPlotConfig(
                                    numeric=cd.TimeSeriesNumericPlot(
                                        color=CHANNEL_PALETTE[i % len(CHANNEL_PALETTE)],
                                        line_style=cd.LineStyle(v1=cd.LineStyleV1.SOLID),
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


def _histogram(channels: list[str], title: str) -> cd.VizDefinition:
    return cd.VizDefinition(
        histogram=cd.HistogramChartDefinition(
            v1=cd.HistogramChartDefinitionV1(
                title=title,
                display_settings=cd.HistogramDisplaySettings(
                    sort=cd.HistogramSortOrder.VALUE_ASCENDING, stacked=False
                ),
                plots=[
                    cd.HistogramPlot(
                        variable_name=ch,
                        color=CHANNEL_PALETTE[i % len(CHANNEL_PALETTE)],
                        enabled=True,
                    )
                    for i, ch in enumerate(channels)
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


def _value_table(channels: list[str], title: str, columns: int = 3) -> cd.VizDefinition:
    """KPI strip: latest values, 5 sig figs, color threshold bands."""
    cells = []
    for i, ch in enumerate(channels):
        bands = CHANNEL_THRESHOLDS.get(ch)
        cells.append(
            cd.ValueTableGridValueTableCell(
                row=i // columns,
                column=i % columns,
                cell=cd.ValueTableCell(
                    variable_name=ch,
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
    rows = (len(channels) + columns - 1) // columns
    return cd.VizDefinition(
        value_table=cd.ValueTableDefinition(
            v2=cd.ValueTableDefinitionV2(
                title=title,
                show_units=True,
                show_staleness_indicator=False,
                staleness_indicator=cd.ValueTableStalenessConfig(hide_staleness=True),
                layout=cd.ValueTableLayout(
                    grid=cd.ValueTableLayoutGrid(
                        row_count=rows,
                        column_count=columns,
                        show_cell_labels=True,
                        grid_default_cell_configs=cd.ValueTableMultiCellConfig(),
                        column_configs=[],
                        row_configs=[],
                        cells=cells,
                    )
                ),
            )
        )
    )


def _ground_station_features() -> list:
    """Ground-station markers (radio-tower icons) for the geo panel."""
    return [
        cd.GeoCustomFeature(
            point=cd.GeoPoint(
                icon="radio-tower",
                latitude=lat,
                longitude=lon,
                label=name,
                variables=[],
            )
        )
        for name, lat, lon in GROUND_STATIONS
    ]


def _geo(title: str) -> cd.VizDefinition:
    return cd.VizDefinition(
        geo=cd.GeoVizDefinition(
            v1=cd.GeoVizDefinitionV1(
                title=title,
                custom_features=_ground_station_features(),
                base_tileset=cd.GeoBaseTileset.SATELLITE,
                unit_system=cd.GeoUnitSystem.METRIC,
                plots=[
                    cd.GeoPlotFromLatLong(
                        id=str(uuid.uuid4()),
                        label="ground track",
                        enabled=True,
                        latitude_variable_name=GEO_LAT_CHANNEL,
                        longitude_variable_name=GEO_LON_CHANNEL,
                        visualization_options=cd.GeoPlotVisualizationOptions(
                            color="#4C79A8", line_style=cd.GeoLineStyle.SOLID
                        ),
                    )
                ],
            )
        )
    )


def _geo3d(title: str) -> cd.VizDefinition:
    return cd.VizDefinition(
        geo3d=cd.Geo3dDefinition(
            v1=cd.Geo3dDefinitionV1(
                title=title,
                crs=cd.Geo3dCrs(ecef=cd.Geo3dCrsEcef()),
                plots=[
                    cd.GeoPlot3d(
                        plot_id=str(uuid.uuid4()),
                        label="satellite",
                        enabled=True,
                        position=cd.Geo3dPosition(
                            wgs84=cd.Geo3dPositionWgs84(
                                latitude_variable_name=GEO_LAT_CHANNEL,
                                longitude_variable_name=GEO_LON_CHANNEL,
                                height_variable_name=GEO_ALT_CHANNEL,
                            )
                        ),
                        orientation=cd.Geo3dOrientation(
                            principal_axes=cd.Geo3dOrientationPrincipalAxes(
                                heading_variable_name="",
                                pitch_variable_name="",
                                roll_variable_name="",
                            )
                        ),
                        visualization_options=cd.GeoPlot3dVisualizationOptions(
                            color="#4C79A8",
                            line_style=cd.GeoLine3dStyle.SOLID,
                            model=cd.Geo3dModel(default=cd.Geo3dDefaultModel.SATELLITE),
                        ),
                    )
                ],
            )
        )
    )


# Set via --procedure-execution to pin the Response tab's embedded panel
# to a live execution. Galaxy's procedure panel only binds V1
# executionRid (the V2 template reference maps to undefined — renders
# an unbound panel), so pin the current execution during demo prep.
PROCEDURE_EXECUTION_RID: str | None = None


def _procedure_panel(title: str) -> cd.VizDefinition:
    """Embedded anomaly-response procedure execution panel."""
    if PROCEDURE_EXECUTION_RID:
        return cd.VizDefinition(
            procedure=cd.ProcedureVizDefinition(
                v1=cd.ProcedureVizDefinitionV1(
                    title=title, execution_rid=PROCEDURE_EXECUTION_RID
                )
            )
        )
    return cd.VizDefinition(
        procedure=cd.ProcedureVizDefinition(
            v2=cd.ProcedureVizDefinitionV2(
                title=title,
                procedure=cd.ProcedureVizId(template_rid=PROCEDURE_RID),
            )
        )
    )


def _log_panel(title: str) -> cd.VizDefinition:
    return cd.VizDefinition(
        log=cd.LogPanelDefinition(
            v1=cd.LogPanelDefinitionV1(
                title=title,
                log_channels=[],
                log_channels_v2=[
                    cd.LogChannel(
                        log_channel_variable_name=LOG_CHANNEL,
                        visible_log_column_names=[],
                        tag_filters={},
                    )
                ],
            )
        )
    )


# ---------------------------------------------------------------- layout


def _canvas_tab(title: str, placed: list[tuple[str, float, float, float, float]]) -> sl.SingleTab:
    """placed: (chart_id, x, y, w, h) in canvas pixels (~1600-wide grid)."""
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


# --------------------------------------------------------------- content


def build_workbook_content(asset_rid: str, sat_no: int):
    """Returns (content_v2, layout). Everything routes through one data
    scope input keyed by the asset rid (swap the satellite from the input
    picker and every panel follows)."""
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
    )
    numeric_channels = numeric_channels + [HTR_CHANNEL]
    channel_variables = {ch: _channel_variable(ch, asset_rid) for ch in numeric_channels}
    channel_variables[LOG_CHANNEL] = _channel_variable(LOG_CHANNEL, asset_rid, kind="log")
    channel_variables[BUS_POWER_VAR] = _bus_power_variable(asset_rid)
    channel_variables[RADIATOR_EQ_VAR] = _radiator_eq_variable(asset_rid)

    charts: dict[str, cd.VizDefinition] = {}

    def add(viz: cd.VizDefinition) -> str:
        cid = str(uuid.uuid4())
        charts[cid] = viz
        return cid

    shell = (sat_no - 1) // 5 + 1
    overview_md = add(
        _markdown(
            f"# GOCE-{sat_no} bus health deep-dive\n\n"
            f"Live single-satellite ops view (plane {shell} of {NUM_SHELLS}). "
            "The satellite is a **data scope input** — swap it from the input "
            "picker to retarget every panel. Redline limits are drawn on the "
            "charts and enforced by the checklist "
            f"**{CHECKLIST_TITLE}**.",
            "Overview",
        )
    )
    health_vt = add(_value_table(HEALTH_GLANCE_CHANNELS, "Bus health at a glance", columns=3))
    alt_ts = add(
        _time_series(
            [GEO_ALT_CHANNEL],
            "Altitude [km]",
            thresholds=[(LIMIT_ALT_BOX_HIGH_KM, "orbit box ceiling", HEX_ALARM, False)],
        )
    )
    ground = add(_geo("Ground track"))
    orbit3d = add(_geo3d("3D orbit"))
    ecef_pos = add(_time_series([c for c, _ in ORBIT_CHANNELS], "ECEF position [m]"))
    ecef_vel = add(_time_series(VELOCITY_CHANNELS, "ECEF velocity [m/s]"))

    thermal_vt = add(_value_table(THERMAL_GLANCE_CHANNELS, "Latest temperatures", columns=3))
    bus_temps = add(
        _time_series(
            BUS_TEMP_CHANNELS,
            "Bus temperatures [°C]",
            thresholds=[(LIMIT_BUS_TEMP_HOT_C, "hot limit", HEX_ALARM, False)],
        )
    )
    struct_temps = add(_time_series(STRUCT_TEMP_CHANNELS, "Structure temperatures [°C]"))
    panel_temps = add(
        _time_series(
            PANEL_TEMP_CHANNELS,
            "Solar panel temperatures [°C]",
            thresholds=[(LIMIT_PANEL_SUSTAINED_C, "sustained-heat limit", HEX_WARN, False)],
        )
    )
    temp_hist = add(_histogram(BUS_TEMP_CHANNELS, "Bus temperature distribution"))

    power_vt = add(_value_table(POWER_GLANCE_CHANNELS, "Latest EPS readouts", columns=3))
    volts = add(
        _time_series(
            BUS_VOLTAGE_CHANNELS,
            "Bus voltages [V]",
            thresholds=[(LIMIT_BUS_UNDERVOLT_V, "undervolt limit", HEX_ALARM, False)],
        )
    )
    currents = add(
        _time_series(
            BUS_CURRENT_CHANNELS,
            "Load currents [A]",
            thresholds=[(LIMIT_BUS_OVERCURRENT_A, "overcurrent limit", HEX_ALARM, False)],
        )
    )
    rails = add(_time_series(POWER_RAIL_CHANNELS, "Power rails"))
    current_hist = add(_histogram(BUS_CURRENT_CHANNELS, "Load current distribution"))

    wheels = add(
        _time_series(
            WHEEL_CHANNELS,
            "Reaction wheel speeds [rpm]",
            thresholds=[(LIMIT_WHEEL_SATURATION_RPM, "saturation", HEX_ALARM, True)],
        )
    )
    accels = add(_time_series(ACCEL_CHANNELS, "Accelerometers"))
    mags = add(_time_series(MAG_CHANNELS, "Magnetometers"))
    subpoint = add(_time_series([GEO_LAT_CHANNEL, GEO_LON_CHANNEL], "Sub-satellite point [deg]"))

    logs = add(_log_panel("Spacecraft logs"))
    wheels_ctx = add(_time_series(WHEEL_CHANNELS, "Wheel speeds (context)"))

    # ------------------------- EPS anomaly RCA tab (the demo drill-down)
    rca_md = add(
        _markdown(
            "# EPS anomaly — root cause drill-down\n\n"
            "**Symptom** (from Fleet status / checklist): bus overcurrent "
            f"(> {LIMIT_BUS_OVERCURRENT_A} A), bus voltage sag "
            f"(< {LIMIT_BUS_UNDERVOLT_V} V), bus temperature climbing.\n\n"
            "**UDFs from first principles — build them live:**\n\n"
            "*Step 1 — bus power.* Excess load is a power problem: "
            "`eps.bus.power_w = eps.bus.voltage_v × eps.bus.current_a`. "
            "Nominal ~9 W median; under fault it rides **~3 W higher**, "
            "breaching the 12 W EPS budget at load peaks. That excess is "
            "exactly HTR-2's rated draw, and "
            "`tcs.htr2.duty_cycle_pct` is pinned at 100%: the heater "
            "controller is latched.\n\n"
            "*Step 2 — can the radiator reject it?* Stefan–Boltzmann: a "
            "radiator in vacuum rejects `P = ε·σ·A·T⁴`, so its "
            "equilibrium is\n\n"
            "&nbsp;&nbsp;&nbsp;&nbsp;**T_eq = (P / (ε·σ·A))^¼** − 273.15\n\n"
            f"with σ = {STEFAN_BOLTZMANN_W_M2K4:.3e} W/m²K⁴, ε = "
            f"{RADIATOR_EMISSIVITY}, A = {RADIATOR_AREA_M2} m² (thermal "
            "model values). Compose it from stock nodes: multiply → scale "
            "by 1/(ε·σ·A) → √ → √ → offset −273.15 "
            "(`tcs.radiator.predicted_eq_temp_c`, saved on this tab).\n\n"
            "*The punchline*: at nominal ~9 W the law predicts −25 °C — "
            "matching the measured radiator exactly. At fault power it "
            "predicts **−10 °C or warmer**, but the radiator still reads −25 °C: "
            "the bus **cannot radiate the extra ~3.3 W**, which is why "
            "`tcs.bus.temp_c` climbs toward the hot limit. The heater "
            "must be commanded off — thermal control can't save it.\n\n"
            "**Corroborate**: fault logs below, then the TVAC "
            "run-comparison workbook. Known corrective action: "
            "`HTR2_PWR_CYCLE` (see the anomaly response procedure).",
            "RCA talk track",
        )
    )
    rca_current = add(
        _time_series(
            [BUS_CURRENT, PAYLOAD_CURRENT],
            "Bus & payload current [A]",
            thresholds=[(LIMIT_BUS_OVERCURRENT_A, "overcurrent limit", HEX_ALARM, True)],
        )
    )
    rca_voltage = add(
        _time_series(
            [BUS_VOLTAGE],
            "Main bus voltage [V]",
            thresholds=[(LIMIT_BUS_UNDERVOLT_V, "undervolt limit", HEX_ALARM, True)],
        )
    )
    rca_power = add(
        _time_series(
            [BUS_POWER_VAR],
            "Bus power P = V × I [W] (UDF)",
            thresholds=[(LIMIT_BUS_POWER_BUDGET_W, "EPS power budget", HEX_ALARM, True)],
        )
    )
    rca_duty = add(
        _time_series(
            [HTR_CHANNEL],
            "HTR-2 heater duty cycle [%] — the smoking gun",
            thresholds=[(LIMIT_HTR_DUTY_LATCHED_PCT, "latched threshold", HEX_ALARM, True)],
        )
    )
    rca_temp = add(
        _time_series(
            [BUS_TEMP, "tcs.pcdu.temp_c"],
            "Bus & PCDU temperature [°C]",
            thresholds=[(LIMIT_BUS_TEMP_HOT_C, "hot limit", HEX_ALARM, False)],
        )
    )
    rca_radiator = add(
        _time_series(
            [RADIATOR_EQ_VAR, MEASURED_RADIATOR],
            "Radiator: Stefan–Boltzmann predicted equilibrium vs measured [°C]",
        )
    )
    rca_logs = add(_log_panel("Fault event log"))

    # Response tab: the anomaly-response procedure embedded beside the
    # live channels it gates on — execute the corrective action without
    # leaving the workbook.
    resp_procedure = add(
        _procedure_panel("Corrective action — GOCE anomaly response (HTR2_PWR_CYCLE)")
    )
    resp_duty = add(
        _time_series(
            [HTR_CHANNEL],
            "HTR-2 duty [%] — watch the command land",
            thresholds=[(LIMIT_HTR_DUTY_LATCHED_PCT, "latched threshold", HEX_ALARM, True)],
        )
    )
    resp_current = add(
        _time_series(
            [BUS_CURRENT],
            "Bus current [A] — recovery gate channel",
            thresholds=[(LIMIT_BUS_OVERCURRENT_A, "overcurrent limit", HEX_ALARM, True)],
        )
    )
    resp_logs = add(_log_panel("Command ACK / fault log"))

    W = 1600.0
    layout = sl.WorkbookLayout(
        v1=sl.WorkbookLayoutV1(
            root_panel=sl.Panel(
                tabbed=sl.TabbedPanel(
                    v1=sl.TabbedPanelV1(
                        id=str(uuid.uuid4()),
                        tabs=[
                            _canvas_tab(
                                "Overview",
                                [
                                    (overview_md, 0, 0, W / 2, 160),
                                    (health_vt, W / 2, 0, W / 2, 380),
                                    (alt_ts, 0, 160, W / 2, 220),
                                    (ground, 0, 380, W / 2, 420),
                                    (orbit3d, W / 2, 380, W / 2, 420),
                                ],
                            ),
                            _canvas_tab(
                                "Orbit",
                                [
                                    (orbit3d, 0, 0, W / 2, 460),
                                    (ground, W / 2, 0, W / 2, 460),
                                    (ecef_pos, 0, 460, W / 2, 340),
                                    (ecef_vel, W / 2, 460, W / 2, 340),
                                ],
                            ),
                            _canvas_tab(
                                "Thermal",
                                [
                                    (thermal_vt, 0, 0, W, 200),
                                    (bus_temps, 0, 200, W / 2, 330),
                                    (struct_temps, W / 2, 200, W / 2, 330),
                                    (panel_temps, 0, 530, W / 2, 330),
                                    (temp_hist, W / 2, 530, W / 2, 330),
                                ],
                            ),
                            _canvas_tab(
                                "Power",
                                [
                                    (power_vt, 0, 0, W, 200),
                                    (volts, 0, 200, W / 2, 330),
                                    (currents, W / 2, 200, W / 2, 330),
                                    (rails, 0, 530, W / 2, 330),
                                    (current_hist, W / 2, 530, W / 2, 330),
                                ],
                            ),
                            _canvas_tab(
                                "EPS anomaly (RCA)",
                                [
                                    (rca_md, 0, 0, W / 2, 560),
                                    (rca_duty, W / 2, 0, W / 2, 280),
                                    (rca_power, W / 2, 280, W / 2, 280),
                                    (rca_current, 0, 560, W / 3, 320),
                                    (rca_voltage, W / 3, 560, W / 3, 320),
                                    (rca_radiator, 2 * W / 3, 560, W / 3, 320),
                                    (rca_temp, 0, 880, W / 2, 300),
                                    (rca_logs, W / 2, 880, W / 2, 300),
                                ],
                            ),
                            _canvas_tab(
                                "Response",
                                [
                                    (resp_procedure, 0, 0, 1000, 880),
                                    (resp_duty, 1000, 0, 600, 300),
                                    (resp_current, 1000, 300, 600, 290),
                                    (resp_logs, 1000, 590, 600, 290),
                                ],
                            ),
                            _canvas_tab(
                                "AOCS",
                                [
                                    (wheels, 0, 0, W / 2, 440),
                                    (accels, W / 2, 0, W / 2, 440),
                                    (mags, 0, 440, W / 2, 440),
                                    (subpoint, W / 2, 440, W / 2, 440),
                                ],
                            ),
                            _canvas_tab(
                                "Logs",
                                [
                                    (logs, 0, 0, W, 560),
                                    (wheels_ctx, 0, 560, W, 320),
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
                    asset_rid: wc.WorkbookDataScopeInput(
                        name="Satellite",
                        label="Satellite",
                        value=wc.DataScopeInputValue(
                            asset=wc.AssetDataScopeInputValue(asset_rid=asset_rid)
                        ),
                        color_mode=wc.WorkbookDataScopeInputColorMode(
                            by_series=wc.BySeriesColorMode()
                        ),
                    )
                }
            )
        ),
    )
    return wc.UnifiedWorkbookContent(workbook=content), layout


# -------------------------------------------------------------- checklist


def _locator(channel: str) -> scout_checks_api.UnresolvedVariableLocator:
    return scout_checks_api.UnresolvedVariableLocator(
        series=scout_api.ChannelLocator(channel=channel, data_source_ref=DATA_SCOPE_NAME, tags={})
    )


def _raw(name: str) -> sc.NumericSeries:
    return sc.NumericSeries(raw=sc.Reference(name=name))


def _threshold_ranges(
    channel: str,
    operator: sc.ThresholdOperator,
    value: float,
    min_duration_s: int | None = None,
) -> sc.RangeSeries:
    persistence = None
    if min_duration_s is not None:
        persistence = sc.PersistenceWindowConfiguration(
            output_range_start=sc.OutputRangeStart(
                first_point_matching_condition=sc.FirstPointMatchingCondition()
            ),
            min_duration=sc.DurationConstant(
                literal=scout_run_api.Duration(seconds=min_duration_s, nanos=0)
            ),
        )
    return sc.RangeSeries(
        threshold=sc.ThresholdingRanges(
            input=_raw(channel),
            operator=operator,
            threshold=sc.DoubleConstant(literal=float(value)),
            persistence_window_configuration=persistence,
        )
    )


def _check(
    title: str,
    description: str,
    priority: scout_api.Priority,
    ranges: sc.RangeSeries,
    channels: list[str],
) -> scout_checks_api.CreateChecklistEntryRequest:
    return scout_checks_api.CreateChecklistEntryRequest(
        create_check=scout_checks_api.CreateCheckRequest(
            title=title,
            description=description,
            priority=priority,
            condition=scout_checks_api.UnresolvedCheckCondition(
                num_ranges_v3=scout_checks_api.UnresolvedNumRangesConditionV3(
                    ranges=ranges,
                    function_spec={},
                    threshold=0,
                    operator=sc.ThresholdOperator.GREATER_THAN,
                    variables={ch: _locator(ch) for ch in channels},
                )
            ),
            generated_event_labels=["GOCE", "bus-health"],
        )
    )


def build_checks() -> list[scout_checks_api.CreateChecklistEntryRequest]:
    op = sc.ThresholdOperator
    pr = scout_api.Priority
    return [
        _check(
            "HTR-2 heater not latched (duty < 60% sustained)",
            "Fails if tcs.htr2.duty_cycle_pct stays above "
            f"{LIMIT_HTR_DUTY_LATCHED_PCT:.0f}% for a sustained 30 seconds — "
            "closed-loop control never holds that duty; this is the "
            "heater-controller latch-up signature (corrective action: "
            "HTR2_PWR_CYCLE).",
            pr.P1,
            _threshold_ranges(
                HTR_CHANNEL, op.GREATER_THAN, LIMIT_HTR_DUTY_LATCHED_PCT, min_duration_s=30
            ),
            [HTR_CHANNEL],
        ),
        _check(
            f"Bus voltage above {LIMIT_BUS_UNDERVOLT_V} V undervolt limit",
            f"Fails if eps.bus.voltage_v drops below {LIMIT_BUS_UNDERVOLT_V} V "
            "at any point.",
            pr.P1,
            _threshold_ranges(BUS_VOLTAGE, op.LESS_THAN, LIMIT_BUS_UNDERVOLT_V),
            [BUS_VOLTAGE],
        ),
        _check(
            f"Bus current below {LIMIT_BUS_OVERCURRENT_A} A overcurrent limit",
            f"Fails if eps.bus.current_a exceeds {LIMIT_BUS_OVERCURRENT_A} A.",
            pr.P1,
            _threshold_ranges(BUS_CURRENT, op.GREATER_THAN, LIMIT_BUS_OVERCURRENT_A),
            [BUS_CURRENT],
        ),
        _check(
            f"Bus power within the {LIMIT_BUS_POWER_BUDGET_W} W EPS budget (computed V × I)",
            "Computed check — bus power is not telemetered; it is derived "
            "in-check as eps.bus.voltage_v × eps.bus.current_a (same "
            "first-principles UDF as the RCA workbook). Fails above "
            f"{LIMIT_BUS_POWER_BUDGET_W} W.",
            pr.P2,
            sc.RangeSeries(
                threshold=sc.ThresholdingRanges(
                    input=sc.NumericSeries(
                        product=sc.ProductSeries(
                            inputs=[_raw(BUS_VOLTAGE), _raw(BUS_CURRENT)]
                        )
                    ),
                    operator=op.GREATER_THAN,
                    threshold=sc.DoubleConstant(literal=LIMIT_BUS_POWER_BUDGET_W),
                )
            ),
            [BUS_VOLTAGE, BUS_CURRENT],
        ),
        _check(
            f"Payload feed below {LIMIT_PAYLOAD_OVERCURRENT_A} A",
            f"Fails if eps.payload.current_a exceeds {LIMIT_PAYLOAD_OVERCURRENT_A} A.",
            pr.P2,
            _threshold_ranges(PAYLOAD_CURRENT, op.GREATER_THAN, LIMIT_PAYLOAD_OVERCURRENT_A),
            [PAYLOAD_CURRENT],
        ),
        _check(
            f"Bus temperature below {LIMIT_BUS_TEMP_HOT_C} °C hot limit",
            f"Fails if tcs.bus.temp_c exceeds {LIMIT_BUS_TEMP_HOT_C} °C.",
            pr.P2,
            _threshold_ranges(BUS_TEMP, op.GREATER_THAN, LIMIT_BUS_TEMP_HOT_C),
            [BUS_TEMP],
        ),
        _check(
            f"Radiator panel below {LIMIT_RADIATOR_WARM_C} °C",
            "Fails if tcs.structure.radiator_temp_c warms above "
            f"{LIMIT_RADIATOR_WARM_C} °C — radiator degradation or excess "
            "dissipation.",
            pr.P2,
            _threshold_ranges(
                "tcs.structure.radiator_temp_c", op.GREATER_THAN, LIMIT_RADIATOR_WARM_C
            ),
            ["tcs.structure.radiator_temp_c"],
        ),
        _check(
            f"No reaction wheel at saturation ({LIMIT_WHEEL_SATURATION_RPM:.0f} rpm)",
            "Fails if ANY of the four wheels or the spare "
            f"(aocs.rw.*) exceeds {LIMIT_WHEEL_SATURATION_RPM:.0f} rpm.",
            pr.P1,
            sc.RangeSeries(
                union_range=sc.UnionRanges(
                    inputs=[
                        _threshold_ranges(ch, op.GREATER_THAN, LIMIT_WHEEL_SATURATION_RPM)
                        for ch in WHEEL_CHANNELS
                    ]
                )
            ),
            list(WHEEL_CHANNELS),
        ),
        _check(
            f"Altitude inside the {LIMIT_ALT_BOX_LOW_KM:.0f}-{LIMIT_ALT_BOX_HIGH_KM:.0f} km orbit box",
            "Fails if the sub-satellite altitude leaves the "
            f"{LIMIT_ALT_BOX_LOW_KM:.0f}-{LIMIT_ALT_BOX_HIGH_KM:.0f} km "
            "station-keeping box.",
            pr.P3,
            sc.RangeSeries(
                min_max_threshold=sc.MinMaxThresholdRanges(
                    input=_raw(GEO_ALT_CHANNEL),
                    lower_bound=sc.DoubleConstant(literal=LIMIT_ALT_BOX_LOW_KM),
                    upper_bound=sc.DoubleConstant(literal=LIMIT_ALT_BOX_HIGH_KM),
                    operator=sc.MinMaxThresholdOperator.OUTSIDE_BOUNDS,
                )
            ),
            [GEO_ALT_CHANNEL],
        ),
        _check(
            f"Solar panel temp not above {LIMIT_PANEL_SUSTAINED_C} °C for more than 60 s",
            "Fails if tcs.solar_panel.wing_a_inner_temp_c stays above "
            f"{LIMIT_PANEL_SUSTAINED_C} °C for a sustained 60 seconds — "
            "transient spikes are tolerated.",
            pr.P2,
            _threshold_ranges(
                "tcs.solar_panel.wing_a_inner_temp_c",
                op.GREATER_THAN,
                LIMIT_PANEL_SUSTAINED_C,
                min_duration_s=60,
            ),
            ["tcs.solar_panel.wing_a_inner_temp_c"],
        ),
    ]


# ---------------------------------------------------------------- driver


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="goce_streamer")
    parser.add_argument("--satellite", type=int, default=1)
    parser.add_argument(
        "--procedure-execution",
        default=None,
        help="Pin the Response tab's embedded procedure panel to this "
        "execution rid (demo prep: create the execution, then re-run "
        "with this flag)",
    )
    args = parser.parse_args()
    if args.procedure_execution:
        global PROCEDURE_EXECUTION_RID
        PROCEDURE_EXECUTION_RID = args.procedure_execution

    client = NominalClient.from_profile(args.profile)
    c = client._clients
    user = client.get_user()
    print(f"Authenticated as: {user.email}")

    name = f"GOCE-{args.satellite}"
    assets = client.search_assets(search_text=name, properties={"asset_id": name})
    asset = next((a for a in assets if a.name == name), None)
    if asset is None:
        raise SystemExit(f"Asset {name} not found — start the streamer first")
    print(f"Target asset: {asset.name} ({asset.rid})")

    # --- workbook ---
    title = WORKBOOK_TITLE.format(n=args.satellite)
    content_v2, layout = build_workbook_content(asset.rid, args.satellite)
    existing = next((w for w in client.search_workbooks(exact_match=title) if w.title == title), None)
    if existing is None:
        req = scout_notebook_api.CreateNotebookRequest(
            title=title,
            description=(
                f"Canvas ops deep-dive for {name}: orbit, thermal, power, AOCS, "
                "logs — satellite swappable via data scope input."
            ),
            is_draft=False,
            state_as_json="{}",
            layout=layout,
            content_v2=content_v2,
            data_scope=scout_notebook_api.NotebookDataScope(asset_rids=[asset.rid]),
            event_refs=[],
            workspace=c.resolve_default_workspace_rid(),
        )
        nb = c.notebook.create(c.auth_header, req)
        wb = client.get_workbook(nb.rid)
        print(f"Created workbook: {title} ({nb.rid})")
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
        print(f"Updated workbook in place: {title} ({existing.rid})")

    # verify
    check = c.notebook.get(c.auth_header, wb.rid)
    n_charts = len(check.content_v2.workbook.charts) if check.content_v2 else 0
    print(f"Verified: {n_charts} charts on server")

    # --- checklist ---
    existing_cl = next(
        (x for x in client.search_checklists(search_text=CHECKLIST_TITLE) if x.name == CHECKLIST_TITLE),
        None,
    )
    if existing_cl is None:
        cl_req = scout_checks_api.CreateChecklistRequest(
            title=CHECKLIST_TITLE,
            description=(
                "Bus health limits for a GOCE satellite: HTR-2 latch-up, EPS "
                "voltage/current/power budget, thermal, reaction wheel "
                "saturation, and orbit box. Run/asset-agnostic via the "
                "'data' data-source ref. Limits from goce_limits.py."
            ),
            assignee_rid=user.rid,
            commit_message="Initial: 10 bus-health checks (hierarchical channel namespace)",
            checks=build_checks(),
            checklist_variables=[],
            labels=["GOCE"],
            properties={"source": "goce_deepdive_builder.py"},
            is_published=True,
            workspace=c.resolve_default_workspace_rid(),
        )
        cl_raw = c.checklist.create(c.auth_header, cl_req)
        checklist = client.get_checklist(cl_raw.rid)
        print(f"Created checklist: {CHECKLIST_TITLE} ({checklist.rid})")
    else:
        # Edit-in-place: cut a new revision on the existing rid (the
        # commit is full-state — the checks below replace the set).
        checklist = existing_cl
        commit_req = scout_checks_api.CommitChecklistRequest(
            checklist_variables=[],
            checks=[
                scout_checks_api.UpdateChecklistEntryRequest(create_check=e.create_check)
                for e in build_checks()
            ],
            commit_message=(
                "Hierarchical channel namespace + retuned limits; added "
                "HTR-2 latch-up and computed bus-power (V x I) checks"
            ),
        )
        c.checklist.commit(c.auth_header, checklist.rid, commit_req)
        print(f"Committed new revision to checklist: {CHECKLIST_TITLE} ({checklist.rid})")

    print("\n=== URLs ===")
    print(f"Workbook:  {wb.nominal_url}")
    print(f"Checklist: {checklist.nominal_url}")


if __name__ == "__main__":
    main()
