#!/usr/bin/env python3
"""Build the "UAV Requirements Verification Campaign" workbook (gov staging).

Asset-scoped live dashboard over UAV-1: one Overview tab (campaign explainer,
headline value table, hero power-margin chart with its verification redline)
plus one tab per system-requirement tree, each mixing a threshold-colored
value table, grouped time-series panels with redlines drawn at the published
check thresholds, and a histogram. Every panel routes through one data scope
input keyed by the asset rid, so the article is swappable from the input
picker.

Thresholds are derived from uav_limits.REQUIREMENT_TRIGGERS — the same single
source the Crux checks and published checklists compile from, so chart
redlines can never drift from what the checklists enforce.

Idempotent: updates the existing workbook by title if present.
"""

from __future__ import annotations

import json
import pathlib
import uuid

from nominal.core import NominalClient
from nominal_api import (
    scout_api,
    scout_channelvariables_api,
    scout_chartdefinition_api as cd,
    scout_compute_api as sc,
    scout_layout_api as sl,
    scout_notebook_api,
    scout_workbookcommon_api as wc,
)

from staging_env import PROFILE, WORKSPACE_RID, WORKSPACE_URL
from uav_limits import CHANNELS, REQUIREMENT_TRIGGERS

RIDS_PATH = pathlib.Path(__file__).parent / "uav_rids.json"
WORKBOOK_TITLE = "UAV Requirements Verification Campaign"
DATA_REF = "data"
W = 1600.0

HEX_ALARM = "#D9534F"
HEX_WARN = "#E4A11B"
PALETTE = ["#4E79A7", "#F28E2B", "#59A14F", "#B07AA1", "#76B7B2", "#EDC948"]

# violation threshold per channel (first trigger that names it), + direction
CHANNEL_LIMIT: dict[str, tuple[str, float]] = {}
for _ext, _triggers in REQUIREMENT_TRIGGERS.items():
    for _ch, _op, _th in _triggers:
        CHANNEL_LIMIT.setdefault(_ch, (_op, _th))


def _bands(channel: str) -> list[tuple[float, str, str]] | None:
    """Ascending (value, color, label) bands; color applies at-or-above."""
    limit = CHANNEL_LIMIT.get(channel)
    if limit is None:
        return None
    op, threshold = limit
    _, base, _amp = CHANNELS[channel]
    if op in (">", ">="):  # high is bad
        return [
            (-1e9, "green", "nominal"),
            (base + 0.6 * (threshold - base), "yellow", "approaching limit"),
            (threshold, "red", "violation"),
        ]
    return [  # low is bad
        (-1e9, "red", "violation"),
        (threshold, "yellow", "low margin"),
        (threshold + 0.4 * (base - threshold), "green", "nominal"),
    ]


def _channel_variable(channel: str, input_key: str):
    lit = sc.StringConstant
    node = sc.ComputeNode(
        numeric=sc.NumericSeries(
            channel=sc.ChannelSeries(
                asset=sc.AssetChannel(
                    asset_rid=lit(variable=input_key),
                    data_scope_name=lit(literal=DATA_REF),
                    channel=lit(literal=channel),
                    additional_tags={},
                    group_by_tags=[],
                    tags_to_group_by=[],
                )
            )
        )
    )
    return scout_channelvariables_api.ChannelVariable(
        variable_name=channel,
        display_name=channel,
        compute_spec=scout_channelvariables_api.ComputeSpec(v1="{}"),
        compute_spec_v2=scout_channelvariables_api.ComputeNodeWithContext(
            compute_node=node,
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


def _redlines(axis_id: str, lines: list[tuple[float, str, str]]):
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
                        line_style=cd.ThresholdLineStyle.DOTTED,
                    )
                    for value, label, color in lines
                ],
                shading_config=cd.ThresholdShadingConfig.NONE,
            )
        ),
    )


def _time_series(channels: list[str], title: str, with_limits: bool = True) -> cd.VizDefinition:
    axis_id = str(uuid.uuid4())
    lines: list[tuple[float, str, str]] = []
    if with_limits:
        seen = set()
        for ch in channels:
            limit = CHANNEL_LIMIT.get(ch)
            if limit and limit[1] not in seen:
                seen.add(limit[1])
                lines.append((limit[1], HEX_ALARM, f"check limit ({ch.split('.')[0]})"))
    return cd.VizDefinition(
        time_series=cd.TimeSeriesChartDefinition(
            v1=cd.TimeSeriesChartDefinitionV1(
                title=title,
                comparison_run_groups=[],
                value_axes=[_value_axis(axis_id, title)],
                thresholds=([_redlines(axis_id, lines)] if lines else []),
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
                                        color=PALETTE[i % len(PALETTE)],
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
                        variable_name=ch, color=PALETTE[i % len(PALETTE)], enabled=True
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
    cells = []
    for i, ch in enumerate(channels):
        bands = _bands(ch)
        cells.append(
            cd.ValueTableGridValueTableCell(
                row=i // columns,
                column=i % columns,
                cell=cd.ValueTableCell(
                    variable_name=ch,
                    uuid=str(uuid.uuid4()),
                    config=cd.ValueTableCellConfig(
                        numeric=cd.NumericCellConfig(
                            number_format=cd.NumberFormat(sig_figs=4),
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


TREES = {
    "Flight stability (SYS-REQ-001)": {
        "table": [
            "fcs.att_err_deg", "fcs.roll_rate_dps", "fcs.recovery_time_s",
            "fcs.ice_index", "ahrs.range_err_m", "fcc.latency_ms",
            "adp.latency_ms", "adp.health_pct", "ahrs.false_alarm_per_hr",
        ],
        "panels": [
            (["fcs.att_err_deg"], "Attitude error [deg]"),
            (["fcs.roll_rate_dps"], "Roll rate [deg/s]"),
            (["fcc.latency_ms", "adp.latency_ms"], "Component latencies [ms]"),
            (["ahrs.range_err_m", "fcc.range_err_m"], "Estimator range errors [m]"),
        ],
        "hist": (["fcs.att_err_deg"], "Attitude error distribution"),
    },
    "GPS-denied navigation (SYS-REQ-002)": {
        "table": [
            "nav.drift_m_per_km", "nav.cep_m", "ins.range_err_m",
            "gnss.range_err_m", "gnss.latency_ms", "ins.false_alarm_per_hr",
        ],
        "panels": [
            (["nav.drift_m_per_km"], "Nav drift [m/km]"),
            (["nav.cep_m"], "Waypoint CEP [m]"),
            (["ins.range_err_m", "gnss.range_err_m"], "INS/GNSS range errors [m]"),
            (["gnss.latency_ms"], "GNSS latency [ms]"),
        ],
        "hist": (["nav.cep_m"], "CEP distribution"),
    },
    "Endurance & power (SYS-REQ-003)": {
        "table": [
            "pwr.margin_pct", "prp.endurance_hr", "prp.restart_time_s",
            "str.latency_ms", "gen.range_err_m", "eng.false_alarm_per_hr",
        ],
        "panels": [
            (["pwr.margin_pct"], "Electrical power margin [%]"),
            (["prp.endurance_hr"], "Projected endurance [h]"),
            (["prp.restart_time_s"], "Engine restart time [s]"),
            (["str.range_err_m", "gen.range_err_m"], "Starter/generator estimator errors [m]"),
        ],
        "hist": (["pwr.margin_pct"], "Power margin distribution"),
    },
    "Detect & avoid (SYS-REQ-004)": {
        "table": [
            "pay.detect_range_km", "pay.eoir_detect_km",
            "pay.track_confidence_pct", "daa.false_alarm_per_hr",
        ],
        "panels": [
            (["pay.detect_range_km"], "Intruder detection range [km]"),
            (["pay.eoir_detect_km"], "EO/IR detection range [km]"),
            (["pay.track_confidence_pct"], "Track confidence [%]"),
            (["daa.false_alarm_per_hr"], "DAA false alarms [1/h]"),
        ],
        "hist": (["pay.detect_range_km", "pay.eoir_detect_km"], "Detection range distribution"),
    },
    "C2 datalink (SYS-REQ-005)": {
        "table": [
            "dl.link_margin_db", "dl.rtb_response_s", "sat.range_err_m",
            "sat.false_alarm_per_hr",
        ],
        "panels": [
            (["dl.link_margin_db"], "C2 link margin [dB]"),
            (["dl.rtb_response_s"], "Lost-link RTB response [s]"),
            (["sat.range_err_m"], "SATCOM range error [m]"),
            (["sat.false_alarm_per_hr"], "SATCOM false alarms [1/h]"),
        ],
        "hist": (["dl.link_margin_db"], "Link margin distribution"),
    },
}

HEADLINE = [
    "pwr.margin_pct", "fcs.att_err_deg", "nav.cep_m",
    "prp.endurance_hr", "pay.detect_range_km", "dl.link_margin_db",
]


def build(asset_rid: str):
    channel_variables = {ch: _channel_variable(ch, asset_rid) for ch in CHANNELS}
    charts: dict[str, cd.VizDefinition] = {}

    def add(viz: cd.VizDefinition) -> str:
        cid = str(uuid.uuid4())
        charts[cid] = viz
        return cid

    overview_md = add(
        _markdown(
            "# Automated requirements verification\n\n"
            "One click of **Execute** verifies the entire UAV requirement "
            "catalog: procedures command each test-case scenario on the live "
            "article, capture a run, and execute the requirement's published "
            "checklist against it — subsystems before the system requirement "
            "they roll up to, five trees in parallel.\n\n"
            "- **Redlines on every chart are the checklist limits** — both "
            "compile from the same source.\n"
            "- Pass/fail rolls up in **Crux Lite** (Apps → Crux Lite) with "
            "zero manual bookkeeping.\n"
            "- Failures halt the campaign and page the team with links to "
            "the failing run and data review.\n",
            "Campaign",
        )
    )
    headline_vt = add(_value_table(HEADLINE, "Headline verification channels", columns=3))
    hero_pwr = add(_time_series(["pwr.margin_pct"], "Electrical power margin [%] — PWR-REQ-001"))
    hero_att = add(_time_series(["fcs.att_err_deg"], "Attitude error [deg] — FCS-REQ-001"))
    context_ts = add(
        _time_series(["flt.altitude_m"], "Altitude [m] — flight context", with_limits=False)
    )
    context_speed = add(
        _time_series(["flt.airspeed_kts"], "Airspeed [kts] — flight context", with_limits=False)
    )

    tabs = [
        _canvas_tab(
            "Overview",
            [
                (overview_md, 0, 0, W / 2, 380),
                (headline_vt, W / 2, 0, W / 2, 380),
                (hero_pwr, 0, 380, W / 2, 300),
                (hero_att, W / 2, 380, W / 2, 300),
                (context_ts, 0, 680, W / 2, 240),
                (context_speed, W / 2, 680, W / 2, 240),
            ],
        )
    ]

    for tab_title, spec in TREES.items():
        vt = add(_value_table(spec["table"], "Latest values vs check limits", columns=3))
        panel_ids = [add(_time_series(chs, t)) for chs, t in spec["panels"]]
        hist = add(_histogram(*spec["hist"]))
        placed = [(vt, 0, 0, W, 260)]
        # 2×2 grid of time series under the table, histogram bottom-left half
        coords = [(0, 260), (W / 2, 260), (0, 590), (W / 2, 590)]
        for pid, (x, y) in zip(panel_ids, coords):
            placed.append((pid, x, y, W / 2, 330))
        placed.append((hist, 0, 920, W / 2, 300))
        tabs.append(_canvas_tab(tab_title, placed))

    layout = sl.WorkbookLayout(
        v1=sl.WorkbookLayoutV1(
            root_panel=sl.Panel(
                tabbed=sl.TabbedPanel(v1=sl.TabbedPanelV1(id=str(uuid.uuid4()), tabs=tabs))
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
                        name="Test article",
                        label="Test article",
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


def main() -> None:
    rids = json.loads(RIDS_PATH.read_text())
    client = NominalClient.from_profile(PROFILE)
    c = client._clients
    content_v2, layout = build(rids["asset_rid"])

    existing = None
    page = c.notebook.search(
        c.auth_header,
        scout_notebook_api.SearchNotebooksRequest(
            query=scout_notebook_api.SearchNotebooksQuery(search_text=WORKBOOK_TITLE),
            show_drafts=True,
            page_size=20,
        ),
    )
    for nb_meta in page.results:
        if nb_meta.metadata.title == WORKBOOK_TITLE:
            existing = nb_meta
            break

    if existing is None:
        req = scout_notebook_api.CreateNotebookRequest(
            title=WORKBOOK_TITLE,
            description=(
                "Live dashboard for the automated requirements-verification "
                "campaign: headline channels, per-tree telemetry with checklist "
                "redlines, and the campaign narrative."
            ),
            is_draft=False,
            state_as_json="{}",
            layout=layout,
            content_v2=content_v2,
            data_scope=scout_notebook_api.NotebookDataScope(asset_rids=[rids["asset_rid"]]),
            event_refs=[],
            workspace=WORKSPACE_RID,
        )
        nb = c.notebook.create(c.auth_header, req)
        rid = nb.rid
        print(f"created workbook {rid}")
    else:
        rid = existing.rid
        nb_raw = c.notebook.get(c.auth_header, rid)
        c.notebook.update(
            c.auth_header,
            scout_notebook_api.UpdateNotebookRequest(
                event_refs=nb_raw.event_refs or [],
                layout=layout,
                state_as_json="{}",
                content_v2=content_v2,
                latest_snapshot_rid=getattr(nb_raw, "snapshot_rid", None),
            ),
            rid,
        )
        print(f"updated workbook {rid}")

    check = c.notebook.get(c.auth_header, rid)
    n_charts = len(check.content_v2.workbook.charts)
    print(f"verified: {n_charts} charts")
    url = f"{WORKSPACE_URL}/workbooks/{rid}"
    rids["workbook_rid"] = rid
    rids["workbook_url"] = url
    RIDS_PATH.write_text(json.dumps(rids, indent=2))
    print(url)


if __name__ == "__main__":
    main()
