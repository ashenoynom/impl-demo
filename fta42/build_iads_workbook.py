#!/usr/bin/env python3
"""Build an IADS-style flight operations workbook in the Demo workspace.

Approach mirrors the regent migration scripts: fetch/compose the workbook's
content_v2 + layout as plain JSON dicts matching the platform Conjure schema
(shapes taken from a working exemplar in the SAME workspace and the regent
FF10 canvas layout), then create/update via the raw NotebookService HTTP
endpoints. Updates use the latestSnapshotRid concurrency guard.

All channel names/data reference ONLY the simulated FTA-42 dataset —
no customer channels are copied.
"""
import json
import os
import sys
import uuid
import copy
import yaml
import requests

SCRATCH = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(SCRATCH, "workbook_state.json")

ASSET_RID = "ri.scout.cerulean-staging.asset.693c2ae4-fed6-4e75-b6ea-79262515cd79"
WS_RID = "ri.security.cerulean-staging.workspace.79c2cdd1-4ccd-4288-b06b-24e902a6b3af"
REF = "flight_telemetry"
NUMERIC_FN_UUID = "e452a338-1ecc-4c4d-ab55-81523a81bc42"
ENUM_FN_UUID = "733b4f9a-d643-432f-9790-0ce6a0223a9d"

cfg = yaml.safe_load(open(os.path.expanduser("~/.config/nominal/config.yml")))
prof = cfg["profiles"]["prod_demo_workspace"]
BASE, TOKEN = prof["base_url"], prof["token"]
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def u():
    return str(uuid.uuid4())

# ================================================================ variables
def channel_var(var, channel, kind="numeric"):
    """ChannelVariable dict — shape mirrors the demo-workspace exemplar."""
    series_type = "numericSeriesType" if kind == "numeric" else "enumSeriesType"
    fn_id = "numericSeries" if kind == "numeric" else "enumSeries"
    fn_uuid = NUMERIC_FN_UUID if kind == "numeric" else ENUM_FN_UUID
    v1 = json.dumps({
        "type": "fn",
        "fn": {"functionId": fn_id, "functionUuid": fn_uuid,
               "args": {"input": {"type": series_type,
                        "provider": {"type": "channel", "channel": {
                            "channelName": channel, "dataSourceRefName": REF,
                            "assetRid": "assetRid", "tagsToGroupBy": []}}}}},
    })
    return {
        "displayName": channel,
        "variableName": var,
        "computeSpec": {"type": "v1", "v1": v1},
        "computeSpecV2": {
            "computeNode": {
                "type": kind,
                kind: {"type": "channel", "channel": {"type": "asset", "asset": {
                    "assetRid": {"type": "variable", "variable": "assetRid"},
                    "dataScopeName": {"type": "literal", "literal": REF},
                    "channel": {"type": "literal", "literal": channel},
                    "additionalTags": {}, "additionalTagFilters": None,
                    "tagsToGroupBy": [], "groupByTags": []}}},
            },
            "context": {"variables": {}},
            "computeExpression": None,
        },
    }

VARS = {  # var -> (channel, kind)
    "ias": "flight.ias_kts", "tas": "flight.tas_kts", "alt": "flight.altitude_ft",
    "ralt": "flight.radalt_ft", "vs": "flight.vspeed_fpm", "mach": "flight.mach",
    "roll": "attitude.roll_deg", "pitch": "attitude.pitch_deg", "hdg": "attitude.heading_deg",
    "aoa": "attitude.aoa_deg", "beta": "attitude.beta_deg",
    "p": "rates.p_dps", "q": "rates.q_dps", "r": "rates.r_dps",
    "nx": "accel.nx_g", "ny": "accel.ny_g", "nz": "accel.nz_g",
    "elev": "controls.elevator_deg", "aill": "controls.aileron_l_deg",
    "ailr": "controls.aileron_r_deg", "rud": "controls.rudder_deg",
    "flap": "controls.flap_deg", "trim": "controls.stab_trim_deg",
    "ecur": "actuators.elev_current_a", "alcur": "actuators.ail_l_current_a",
    "arcur": "actuators.ail_r_current_a", "rcur": "actuators.rud_current_a",
    "etmp": "actuators.elev_temp_c", "altmp": "actuators.ail_l_temp_c",
    "artmp": "actuators.ail_r_temp_c", "rtmp": "actuators.rud_temp_c",
    "rpm": "engine.rpm", "egt": "engine.egt_c", "cht": "engine.cht_c",
    "oilp": "engine.oil_press_psi", "oilt": "engine.oil_temp_c",
    "ff": "engine.fuel_flow_gph", "fq": "engine.fuel_qty_gal",
    "thr": "engine.throttle_pct", "map": "engine.manifold_press_inhg",
    "busv": "elec.bus_volts", "busa": "elec.bus_amps",
    "batv": "elec.batt_volts", "batt": "elec.batt_temp_c",
    "lat": "gps.latitude_deg", "lon": "gps.longitude_deg",
    "gs": "gps.ground_speed_kts", "sats": "gps.num_sats",
    "oat": "env.oat_c", "sp": "env.static_press_psi",
    "tact": "test.test_active",
}
channel_variables = {v: channel_var(v, ch) for v, ch in VARS.items()}
channel_variables["tp"] = channel_var("tp", "test.test_point", kind="enum")

# ================================================================ charts
PALETTE = ["#4fc3f7", "#ffb74d", "#81c784", "#e57373", "#ba68c8",
           "#fff176", "#4db6ac", "#f06292", "#a1887f", "#90a4ae"]

def axis(ax_id, title):
    return {"id": ax_id, "title": title,
            "displayOptions": {"showTitle": False, "axisWidth": None, "scaleType": None},
            "range": {"start": None, "end": None},
            "limit": {"start": None, "end": None},
            "position": "LEFT", "domainType": "NUMERIC",
            "tickNumberFormat": None, "tooltipNumberFormat": None, "reversed": None}

def ts_chart(title, rows):
    """rows: list of (row_title, [(var, color), ...]) — one strip per row."""
    out_rows, axes = [], []
    for row_title, plots in rows:
        ax_id = u()
        axes.append(axis(ax_id, row_title))
        out_rows.append({
            "title": row_title, "plots": [],
            "plotsV2": [{"variableName": v, "enabled": True,
                         "type": {"type": "numeric", "numeric": {
                             "color": c, "lineStyle": {"type": "v1", "v1": "SOLID"}}},
                         "hideFromTooltip": None, "yAxisId": ax_id}
                        for v, c in plots],
            "rowFlexSize": 1.0, "enabled": True})
    return {"type": "timeSeries", "timeSeries": {"type": "v1", "v1": {
        "rows": out_rows, "comparisonRunGroups": [], "events": None,
        "title": title, "valueAxes": axes, "thresholds": [],
        "disconnectedValues": None,
        "stalenessConfiguration": {"threshold": {"seconds": 1, "nanos": 0},
                                   "connectStalePoints": True},
        "plotColoringConfiguration": {"type": "rowIndependent", "rowIndependent": {}},
        "anchorPoint": None, "bucketStrategy": None,
        "floatingLegendsConfig": {"hidden": False,
                                  "legend": {"type": "perRow", "perRow": {"position": None}}},
        "bucketDisplayConfig": None}}}

# --- valueTable: reuse the working exemplar's default-config blocks verbatim
_hitl = json.load(open(os.path.join(SCRATCH, "demo_hitl.json")))
_vt_template = copy.deepcopy(
    [c for c in _hitl["contentV2"]["workbook"]["charts"].values()
     if c["type"] == "valueTable"][0])
_defaults = _vt_template["valueTable"]["v2"]["layout"]["grid"]["gridDefaultCellConfigs"]
# neutral default numeric threshold
_defaults = copy.deepcopy(_defaults)
_defaults["numeric"]["visualisation"]["raw"]["thresholds"] = [
    {"value": 0.0, "color": "green", "label": None, "latch": None}]
# exemplar default rounds to 1 sig fig which clobbers per-cell decimalPlaces
_defaults["numeric"]["numberFormat"] = None

def _line_config():
    """Per-row/column pass-through cell config (mirrors exemplar rows/cols)."""
    return {
        "range": {"visualisation": {"type": "raw", "raw": {
            "rangeColor": None, "rangeLabel": None,
            "noRangeColor": None, "noRangeLabel": None}}, "groupBySort": None},
        "numeric": {"visualisation": None, "numberFormat": None, "groupBySort": None},
        "staleness": None, "numericArray": None, "enumArray": None, "struct": None,
        "enum": {"visualisation": None, "groupBySort": None},
    }

def numeric_cell(var, thresholds=None, decimals=1):
    thr = thresholds or [{"value": 0.0, "color": "green", "label": None, "latch": None}]
    return {"variableName": var, "uuid": u(), "config": {"type": "numeric", "numeric": {
        "visualisation": {"type": "raw", "raw": {"thresholds": thr}},
        "numberFormat": {"sigFigs": 5, "displayOption": None,
                         "fixedDecimalPlaces": decimals,
                         "decimalPlaces": {"type": "fixed", "fixed": {"places": decimals}}},
        "groupBySort": None}}}

def enum_cell(var):
    return {"variableName": var, "uuid": u(), "config": {"type": "enum", "enum": {
        "visualisation": {"type": "raw", "raw": {"colorMap": None}}, "groupBySort": None}}}

def value_table(title, grid_cells, n_cols):
    """grid_cells: list of rows, each a list of cell dicts (or None)."""
    n_rows = len(grid_cells)
    cells = []
    for ri, row in enumerate(grid_cells):
        for ci, cell in enumerate(row):
            if cell is not None:
                cells.append({"row": ri, "column": ci, "cell": cell})
    return {"type": "valueTable", "valueTable": {"type": "v2", "v2": {
        "title": title, "showUnits": True, "showStalenessIndicator": False,
        "layout": {"type": "grid", "grid": {
            "showRowHeaders": False, "rowHeaderWidth": None,
            "showColumnHeaders": False, "showCellLabels": True,
            "gridDefaultCellConfigs": copy.deepcopy(_defaults),
            "columnConfigs": [{"position": i, "header": None, "cellConfig": _line_config()}
                              for i in range(n_cols)],
            "rowConfigs": [{"position": i, "header": None, "cellConfig": _line_config()}
                           for i in range(n_rows)],
            "rowCount": n_rows, "columnCount": n_cols, "cells": cells}},
        "stalenessIndicator": None}}}

def geo_chart(title):
    return {"type": "geo", "geo": {"type": "v1", "v1": {
        "plots": [{"id": u(), "latitudeVariableName": "lat",
                   "longitudeVariableName": "lon",
                   "secondaryVariables": [{"variableName": "alt", "label": None,
                       "enabled": None,
                       "visualizationOption": {"type": "asColors", "asColors": {
                           "type": "numericPreset", "numericPreset": {
                               "low": 2500.0, "high": 9000.0, "preset": "TURBO"}}}}],
                   "enabled": True, "label": None,
                   "visualizationOptions": {"color": "#4fc3f7", "lineStyle": "SOLID",
                       "arrowStyle": "NONE",
                       "secondaryColorVisualization": {"visible": True,
                                                       "variableName": "alt"}}}],
        "backgroundOverlays": [], "title": title, "customFeatures": [],
        "customMeasurements": [], "baseTileset": "STREET",
        "additionalTileset": None, "unitSystem": "METRIC"}}}

C = PALETTE
charts = {}
def add_chart(defn):
    cid = u(); charts[cid] = defn; return cid

# ---- Tab 1: Flight Overview
c_map = add_chart(geo_chart("Flight Track — colored by altitude"))
c_altias = add_chart(ts_chart("Altitude / Airspeed", [
    ("Altitude (ft)", [("alt", C[0]), ("ralt", C[9])]),
    ("Airspeed (kts)", [("ias", C[1]), ("tas", C[2]), ("gs", C[9])]),
]))
c_vsi = add_chart(ts_chart("Vertical Speed / Mach", [
    ("V/S (fpm)", [("vs", C[3])]),
    ("Mach", [("mach", C[4])]),
]))
c_key = add_chart(value_table("Flight State", [
    [numeric_cell("ias", decimals=0), numeric_cell("alt", decimals=0),
     numeric_cell("hdg", decimals=0), numeric_cell("gs", decimals=0)],
    [numeric_cell("nz", decimals=2),
     numeric_cell("aoa", [{"value": 0.0, "color": "green", "label": None, "latch": None},
                          {"value": 12.0, "color": "red", "label": "High AoA", "latch": None}]),
     numeric_cell("fq", [{"value": 15.0, "color": "green", "label": None, "latch": None},
                         {"value": 0.0, "color": "red", "label": "Low fuel", "latch": None}]),
     numeric_cell("sats", decimals=0)],
    [enum_cell("tp"), numeric_cell("tact", decimals=0),
     numeric_cell("oat", decimals=1), numeric_cell("vs", decimals=0)],
], 4))

# ---- Tab 2: Aero & Handling
c_att = add_chart(ts_chart("Attitude", [
    ("Roll (deg)", [("roll", C[0])]),
    ("Pitch (deg)", [("pitch", C[1])]),
    ("Heading (deg)", [("hdg", C[2])]),
]))
c_flow = add_chart(ts_chart("Flow Angles", [
    ("AoA (deg)", [("aoa", C[3])]),
    ("Sideslip (deg)", [("beta", C[4])]),
]))
c_rates = add_chart(ts_chart("Body Rates", [
    ("p (deg/s)", [("p", C[0])]),
    ("q (deg/s)", [("q", C[1])]),
    ("r (deg/s)", [("r", C[2])]),
]))
c_accel = add_chart(ts_chart("Load Factors", [
    ("Nx (g)", [("nx", C[5])]),
    ("Ny (g)", [("ny", C[6])]),
    ("Nz (g)", [("nz", C[7])]),
]))

# ---- Tab 3: Controls & Actuation
c_surf = add_chart(ts_chart("Control Surface Positions", [
    ("Elevator (deg)", [("elev", C[0])]),
    ("Ailerons (deg)", [("aill", C[1]), ("ailr", C[2])]),
    ("Rudder (deg)", [("rud", C[3])]),
    ("Flaps / Trim (deg)", [("flap", C[4]), ("trim", C[5])]),
]))
c_acur = add_chart(ts_chart("Actuator Currents", [
    ("Current (A)", [("ecur", C[0]), ("alcur", C[1]), ("arcur", C[2]), ("rcur", C[3])]),
]))
c_atmp = add_chart(ts_chart("Actuator Temperatures", [
    ("Temp (degC)", [("etmp", C[0]), ("altmp", C[1]), ("artmp", C[2]), ("rtmp", C[3])]),
]))
_act_thr = [{"value": 0.0, "color": "green", "label": None, "latch": None},
            {"value": 8.0, "color": "yellow", "label": "High load", "latch": None},
            {"value": 10.5, "color": "red", "label": "Overcurrent", "latch": None}]
_tmp_thr = [{"value": 0.0, "color": "green", "label": None, "latch": None},
            {"value": 70.0, "color": "yellow", "label": "Warm", "latch": None},
            {"value": 85.0, "color": "red", "label": "Hot", "latch": None}]
c_acttab = add_chart(value_table("Actuator Health", [
    [numeric_cell("ecur", _act_thr), numeric_cell("alcur", _act_thr),
     numeric_cell("arcur", _act_thr), numeric_cell("rcur", _act_thr)],
    [numeric_cell("etmp", _tmp_thr), numeric_cell("altmp", _tmp_thr),
     numeric_cell("artmp", _tmp_thr), numeric_cell("rtmp", _tmp_thr)],
], 4))
c_testtab = add_chart(value_table("Test Card", [
    [enum_cell("tp"), numeric_cell("tact", decimals=0)],
    [numeric_cell("ias", decimals=0), numeric_cell("alt", decimals=0)],
], 2))

# ---- Tab 4: Propulsion & Electrical
c_eng = add_chart(ts_chart("Engine", [
    ("RPM / Throttle", [("rpm", C[0]), ("thr", C[1])]),
    ("EGT / CHT (degC)", [("egt", C[3]), ("cht", C[4])]),
    ("Oil (psi / degC)", [("oilp", C[2]), ("oilt", C[5])]),
]))
c_fuel = add_chart(ts_chart("Fuel", [
    ("Flow (gph)", [("ff", C[6])]),
    ("Quantity (gal)", [("fq", C[7])]),
]))
c_elec = add_chart(ts_chart("Electrical", [
    ("Bus (V / A)", [("busv", C[0]), ("busa", C[1])]),
    ("Battery (V / degC)", [("batv", C[2]), ("batt", C[3])]),
]))
_egt_thr = [{"value": 0.0, "color": "green", "label": None, "latch": None},
            {"value": 830.0, "color": "yellow", "label": "EGT caution", "latch": None},
            {"value": 860.0, "color": "red", "label": "EGT limit", "latch": None}]
c_engtab = add_chart(value_table("Engine Readouts", [
    [numeric_cell("rpm", decimals=0), numeric_cell("thr", decimals=0),
     numeric_cell("egt", _egt_thr), numeric_cell("cht")],
    [numeric_cell("oilp",
        [{"value": 0.0, "color": "red", "label": "Low oil press", "latch": None},
         {"value": 30.0, "color": "green", "label": None, "latch": None}]),
     numeric_cell("oilt"), numeric_cell("ff"), numeric_cell("fq")],
], 4))
c_envtab = add_chart(value_table("Air Data / Electrical", [
    [numeric_cell("oat"), numeric_cell("sp", decimals=2),
     numeric_cell("mach", decimals=3), numeric_cell("map", decimals=1)],
    [numeric_cell("busv"), numeric_cell("busa"),
     numeric_cell("batv"), numeric_cell("batt")],
], 4))

# ================================================================ layout
def panel(x, y, w, h):
    return {"type": "panel", "panel": {"rect": {"x": float(x), "y": float(y),
            "width": float(w), "height": float(h)}, "hideLegend": None}}

def canvas_tab(title, objects):
    return {"type": "v1", "v1": {"title": title, "panel": {
        "type": "canvas", "canvas": {"id": u(), "objects": objects}}}}

layout = {"type": "v1", "v1": {"rootPanel": {"type": "tabbed", "tabbed": {
    "type": "v1", "v1": {"id": u(), "tabs": [
        canvas_tab("Flight Overview", {
            c_map:    panel(0, 0, 640, 560),
            c_altias: panel(640, 0, 960, 560),
            c_key:    panel(0, 560, 640, 340),
            c_vsi:    panel(640, 560, 960, 340),
        }),
        canvas_tab("Aero & Handling", {
            c_att:   panel(0, 0, 800, 600),
            c_flow:  panel(800, 0, 800, 600),
            c_rates: panel(0, 600, 800, 300),
            c_accel: panel(800, 600, 800, 300),
        }),
        canvas_tab("Controls & Actuation", {
            c_surf:    panel(0, 0, 800, 900),
            c_acur:    panel(800, 0, 800, 310),
            c_atmp:    panel(800, 310, 800, 310),
            c_acttab:  panel(800, 620, 520, 280),
            c_testtab: panel(1320, 620, 280, 280),
        }),
        canvas_tab("Propulsion & Electrical", {
            c_eng:    panel(0, 0, 800, 620),
            c_fuel:   panel(800, 0, 800, 310),
            c_elec:   panel(800, 310, 800, 310),
            c_engtab: panel(0, 620, 800, 280),
            c_envtab: panel(800, 620, 800, 280),
        }),
    ]}}}}}

# ================================================================ content
content_v2 = {"type": "workbook", "workbook": {
    "channelVariables": channel_variables,
    "inputs": {"type": "v1", "v1": {"inputs": []}},
    "charts": charts,
    "settings": {
        "assetSettings": None, "runSettings": None,
        "timeSettings": {"type": "v1", "v1": {
            "timeRangeType": "ABSOLUTE", "globalTimeRange": None,
            "isGlobalTime": True, "tabTimeRanges": {}}},
        "offsets": {"type": "v1", "v1": {"runs": {}, "assets": {}, "inputs": None}},
        "defaultStalenessConfiguration": None},
    "dataScopeInputs": {"type": "v1", "v1": {"inputs": {
        ASSET_RID: {"name": "Input 1", "label": "Input 1",
                    "value": {"type": "asset", "asset": {"assetRid": ASSET_RID}},
                    "colorMode": {"type": "bySeries", "bySeries": {}}}}}},
    "reportContent": None,
    "version": None,
}}

TITLE = "IADS Flight Operations — FTA-42 Flight Test (Simulated)"
DESC = ("IADS-style flight test dashboard: strip charts, numeric readouts with "
        "limit thresholds, and moving map. Structure modeled on flight-test "
        "control-room screens; all data simulated (FTA-42 Flight 04).")

def create():
    body = {
        "title": TITLE, "description": DESC,
        "notebookType": "WORKBOOK", "isDraft": False,
        "stateAsJson": "{}", "charts": None, "runRid": None,
        "dataScope": {"type": "assetRids", "assetRids": [ASSET_RID]},
        "layout": layout, "content": None, "contentV2": content_v2,
        "eventRefs": [], "checkAlertRefs": [], "workspace": WS_RID,
    }
    r = requests.post(f"{BASE}/scout/v2/notebook", headers=H, json=body)
    if not r.ok:
        print("CREATE FAILED", r.status_code, r.text[:3000]); sys.exit(1)
    j = r.json()
    json.dump({"rid": j["rid"]}, open(STATE, "w"))
    print("CREATED", j["rid"])
    return j["rid"]

def update(rid):
    # snapshot concurrency guard: fetch latest snapshot rid first
    cur = requests.get(f"{BASE}/scout/v2/notebook/{rid}", headers=H)
    cur.raise_for_status()
    snap = cur.json()["snapshotRid"]
    body = {
        "stateAsJson": "{}", "charts": None,
        "layout": layout, "content": None, "contentV2": content_v2,
        "latestSnapshotRid": snap, "eventRefs": [], "checkAlertRefs": [],
    }
    r = requests.put(f"{BASE}/scout/v2/notebook/{rid}", headers=H, json=body)
    if not r.ok:
        print("UPDATE FAILED", r.status_code, r.text[:3000]); sys.exit(1)
    print("UPDATED", rid, "prev snapshot:", snap)
    return rid

if __name__ == "__main__":
    if os.path.exists(STATE):
        rid = json.load(open(STATE))["rid"]
        update(rid)
    else:
        rid = create()
    print(f"URL: https://app.gov.nominal.io/workbooks/{rid.rsplit('.', 1)[-1]}")
