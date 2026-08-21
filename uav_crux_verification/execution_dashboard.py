#!/usr/bin/env python3
"""Pin a campaign's procedure executions into the campaign workbook.

Adds (or replaces) a "Campaign executions" tab in the "UAV Requirements
Verification Campaign" workbook: one embedded procedure-execution panel per
system tree (the SYS-REQ execution when it exists, else the tree's newest),
plus the failure-track hero (PWR-REQ-001).

Why a repin script: galaxy's procedure panel renders only the V1 variant —
a CONCRETE execution rid (the V2 "template" variant renders unbound), and
every campaign mints fresh executions. Run this right after a campaign
starts (or between the phases / after it ends) to point the tab at that
campaign. KEEP THE WORKBOOK CLOSED while this runs — an open tab can
auto-save stale state over the update.

Usage:
    python3 execution_dashboard.py                  # latest campaign
    python3 execution_dashboard.py --campaign 20260821-1505
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import uuid

from nominal.core import NominalClient
from nominal.core._utils.grpc_tools import create_grpc_channel
from nominal_api import scout_chartdefinition_api as cd
from nominal_api import scout_layout_api as sl
from nominal_api import scout_notebook_api
from nominal.protos.procedures.executions.v1 import procedure_executions_pb2 as pe
from nominal.protos.procedures.executions.v1.procedure_executions_pb2_grpc import (
    ProcedureExecutionsServiceStub,
)

from crux_kv import load_doc
from staging_env import PROFILE, WORKSPACE_URL
from uav_catalog import load_catalog
from uav_limits import FAULT_REQUIREMENT

RIDS_PATH = pathlib.Path(__file__).parent / "uav_rids.json"
TAB_TITLE = "Campaign executions"
TITLE_RE = re.compile(r"^(?P<ext>[A-Z0-9\-]+) — campaign (?P<stamp>[\d\-]+)$")
W = 1600.0


def campaign_executions(execs, stamp: str | None):
    """(stamp, {requirement_ext: (exec_rid, created_at_ns)}) for the newest
    (or requested) campaign."""
    found: dict[str, dict[str, tuple[str, int]]] = {}
    token = ""
    while True:
        req = pe.SearchProcedureExecutionsRequest(
            query=pe.ProcedureExecutionSearchQuery(search_text="campaign"),
            page_size=100,
            **({"page_token": token} if token else {}),
        )
        resp = execs.SearchProcedureExecutions(req)
        for meta in resp.procedure_executions:
            match = TITLE_RE.match(meta.title)
            if not match:
                continue
            run_stamp = match.group("stamp")
            created = meta.created_at.seconds if meta.HasField("created_at") else 0
            bucket = found.setdefault(run_stamp, {})
            ext = match.group("ext")
            if ext not in bucket or created > bucket[ext][1]:
                bucket[ext] = (meta.rid, created)
        token = getattr(resp, "next_page_token", "")
        if not token:
            break
    if not found:
        raise SystemExit("no campaign executions found")
    chosen = stamp or max(found)
    if chosen not in found:
        raise SystemExit(f"campaign {chosen} not found; have: {sorted(found)}")
    return chosen, found[chosen]


def pick_panels(by_ext: dict[str, tuple[str, int]], catalog) -> list[tuple[str, str]]:
    """[(panel title, execution rid)] — one per tree + the fault hero."""
    panels: list[tuple[str, str]] = []
    for root in catalog.roots:
        tree_exts = [r.external_id for r in catalog.tree_schedule(root)]
        rid = None
        chosen_ext = None
        if root.external_id in by_ext:
            chosen_ext, rid = root.external_id, by_ext[root.external_id][0]
        else:
            newest = max(
                ((ext, by_ext[ext]) for ext in tree_exts if ext in by_ext),
                key=lambda item: item[1][1],
                default=None,
            )
            if newest:
                chosen_ext, rid = newest[0], newest[1][0]
        if rid:
            panels.append((f"{root.external_id} tree — {chosen_ext}", rid))
    if FAULT_REQUIREMENT in by_ext and all(
        by_ext[FAULT_REQUIREMENT][0] != rid for _, rid in panels
    ):
        panels.append((f"Failure-track hero — {FAULT_REQUIREMENT}", by_ext[FAULT_REQUIREMENT][0]))
    return panels[:6]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", help="campaign stamp (default: newest)")
    args = parser.parse_args()

    rids = json.loads(RIDS_PATH.read_text())
    client = NominalClient.from_profile(PROFILE)
    b = client._clients
    channel = create_grpc_channel(
        api_base_url=b._api_base_url,
        service_config=b._service_config,
        user_agent=b._user_agent,
        auth_header=b.auth_header,
        header_provider=b.header_provider,
    )
    execs = ProcedureExecutionsServiceStub(channel)

    stamp, by_ext = campaign_executions(execs, args.campaign)
    _, doc = load_doc()
    catalog = load_catalog(doc)
    panels = pick_panels(by_ext, catalog)
    print(f"campaign {stamp}: pinning {len(panels)} executions")
    for title, rid in panels:
        print(f"  {title}: {rid}")

    c = client._clients
    nb_rid = rids["workbook_rid"]
    nb = c.notebook.get(c.auth_header, nb_rid)
    content = nb.content_v2.workbook

    # Drop previous procedure panels, add the new pins.
    old_procedure_charts = {
        chart_id for chart_id, viz in content.charts.items() if viz.procedure is not None
    }
    for chart_id in old_procedure_charts:
        del content.charts[chart_id]
    placed: list[tuple[str, float, float, float, float]] = []
    for i, (title, exec_rid) in enumerate(panels):
        chart_id = str(uuid.uuid4())
        content.charts[chart_id] = cd.VizDefinition(
            procedure=cd.ProcedureVizDefinition(
                v1=cd.ProcedureVizDefinitionV1(title=title, execution_rid=exec_rid)
            )
        )
        col, row = i % 2, i // 2
        placed.append((chart_id, col * (W / 2), row * 480.0, W / 2, 480.0))

    tabs = nb.layout.v1.root_panel.tabbed.v1.tabs
    kept = [tab for tab in tabs if tab.v1.title != TAB_TITLE]
    exec_tab = sl.SingleTab(
        v1=sl.SingleTabV1(
            title=TAB_TITLE,
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
    # Executions tab goes right after Overview.
    new_tabs = kept[:1] + [exec_tab] + kept[1:]
    layout = sl.WorkbookLayout(
        v1=sl.WorkbookLayoutV1(
            root_panel=sl.Panel(
                tabbed=sl.TabbedPanel(
                    v1=sl.TabbedPanelV1(id=nb.layout.v1.root_panel.tabbed.v1.id, tabs=new_tabs)
                )
            )
        )
    )
    c.notebook.update(
        c.auth_header,
        scout_notebook_api.UpdateNotebookRequest(
            event_refs=nb.event_refs or [],
            layout=layout,
            state_as_json="{}",
            content_v2=nb.content_v2,
            latest_snapshot_rid=getattr(nb, "snapshot_rid", None),
        ),
        nb_rid,
    )
    check = c.notebook.get(c.auth_header, nb_rid)
    n_proc = sum(1 for viz in check.content_v2.workbook.charts.values() if viz.procedure is not None)
    print(f"updated: {n_proc} procedure panels, {len(check.layout.v1.root_panel.tabbed.v1.tabs)} tabs")
    print(f"{WORKSPACE_URL}/workbooks/{nb_rid}")


if __name__ == "__main__":
    main()
