#!/usr/bin/env python3
"""Publish every Crux requirement check as a Core checklist (gov staging).

Faithful port of crux-lite's checklist-publish seam
(labs apps/crux-lite/src/host/checklist-publish.ts) through the nominal SDK's
conjure client — the first live exercise of that seam:

- one checklist per requirement, one check per checklist;
- the check's violation tree compiles to a single numRangesV3 condition:
  ranges = union of the violation triggers, threshold 1, GTE — i.e. ">= 1
  range where a trigger holds" fails the run;
- channels resolve through ChannelLocator(data_source_ref="data") so the
  checklist executes against any run whose data scope carries ref "data"
  (our campaign runs will);
- crux identifiers ride in `properties` (the contract has no field for them);
- first publish creates; re-publish commits to the existing rid (lineage
  preserved, `latest_commit` as the concurrency token);
- afterwards the Crux doc's check.publish flips to
  {state: "published", checklistRid, publishedAt} — one doc write.

Usage:
    python3 checklist_publisher.py            # publish/refresh all 36
    python3 checklist_publisher.py --only PWR-REQ-001
"""

from __future__ import annotations

import argparse
import datetime
import re

from nominal.core import NominalClient
from nominal_api.scout_api import ChannelLocator, Priority
from nominal_api.scout_checks_api import (
    CommitChecklistRequest,
    CreateCheckRequest,
    CreateChecklistEntryRequest,
    CreateChecklistRequest,
    UnresolvedCheckCondition,
    UnresolvedNumRangesConditionV3,
    UnresolvedVariableLocator,
    UpdateChecklistEntryRequest,
)
from nominal_api.scout_compute_api import (
    DoubleConstant,
    NumericSeries,
    RangeSeries,
    Reference,
    ThresholdOperator,
    ThresholdingRanges,
    UnionRanges,
)

from crux_kv import load_doc, save_doc
from staging_env import PROFILE, WORKSPACE_RID
from uav_catalog import load_catalog

DATA_REF = "data"

OPERATOR_WIRE = {
    ">": ThresholdOperator.GREATER_THAN,
    ">=": ThresholdOperator.GREATER_THAN_OR_EQUAL_TO,
    "<": ThresholdOperator.LESS_THAN,
    "<=": ThresholdOperator.LESS_THAN_OR_EQUAL_TO,
}


def now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def variable_names(channels: list[str]) -> dict[str, str]:
    """crux-lite's minter: identifier-safe, collision-suffixed."""
    taken: set[str] = set()
    out: dict[str, str] = {}
    for channel in channels:
        if channel in out:
            continue
        base = re.sub(r"^_+|_+$", "", re.sub(r"[^0-9a-zA-Z_]", "_", channel))
        if not re.match(r"^[a-zA-Z]", base):
            base = f"v_{base}"
        name, n = base, 2
        while name in taken:
            name, n = f"{base}_{n}", n + 1
        taken.add(name)
        out[channel] = name
    return out


def build_condition(tree: dict) -> UnresolvedCheckCondition:
    channels = [row["channel"] for row in tree["items"]]
    names = variable_names(channels)
    triggers = [
        RangeSeries(
            threshold=ThresholdingRanges(
                input=NumericSeries(raw=Reference(name=names[row["channel"]])),
                operator=OPERATOR_WIRE[row["operator"]],
                threshold=DoubleConstant(literal=float(row["threshold"])),
            )
        )
        for row in tree["items"]
    ]
    ranges = triggers[0] if len(triggers) == 1 else RangeSeries(
        union_range=UnionRanges(inputs=triggers)
    )
    variables = {
        name: UnresolvedVariableLocator(
            series=ChannelLocator(channel=channel, data_source_ref=DATA_REF, tags={})
        )
        for channel, name in names.items()
    }
    return UnresolvedCheckCondition(
        num_ranges_v3=UnresolvedNumRangesConditionV3(
            function_spec={},
            ranges=ranges,
            operator=ThresholdOperator.GREATER_THAN_OR_EQUAL_TO,
            threshold=1,
            variables=variables,
        )
    )


def check_entry(ext_id: str, title: str, tree: dict) -> CreateCheckRequest:
    # NOTE: no check_lineage_rid — passing the lineage rid read back from a
    # VersionedChecklist makes the commit 400 InvalidArgument (verified live
    # 2026-08-21, contra crux-lite's traced recipe). Omitting it commits fine;
    # the check gets a fresh identity on each re-publish, which we accept.
    rows = ", ".join(
        f"{r['channel']} {r['operator']} {r['threshold']}{r.get('unit', '')}"
        for r in tree["items"]
    )
    return CreateCheckRequest(
        title=f"{ext_id} — {title}",
        description=(
            f'Violation triggers for "{title}" (pass criterion: no_violations). '
            f"Fails when any of: {rows}."
        ),
        priority=Priority.P2,
        condition=build_condition(tree),
        generated_event_labels=[ext_id, "verification"],
    )


def fetch_published_by_external(c) -> dict[str, str]:
    """external id → checklist rid for everything this campaign has published."""
    from nominal_api.api import Property
    from nominal_api.scout_checks_api import ChecklistSearchQuery, SearchChecklistsRequest

    out: dict[str, str] = {}
    token_ = None
    while True:
        page = c.checklist.search(
            c.auth_header,
            SearchChecklistsRequest(
                query=ChecklistSearchQuery(
                    property=Property(name="source", value="crux-lite")
                ),
                page_size=100,
                **({"next_page_token": token_} if token_ else {}),
            ),
        )
        for versioned in page.values:
            ext = (versioned.metadata.properties or {}).get("crux_requirement_external_id")
            if ext:
                out[ext] = versioned.rid
        token_ = page.next_page_token
        if not token_:
            break
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="publish a single requirement external id")
    args = parser.parse_args()

    client = NominalClient.from_profile(PROFILE)
    c = client._clients
    me = client.get_user()

    manifest_entry, doc = load_doc()
    catalog = load_catalog(doc)
    checks_by_req = {chk["requirementId"]: chk for chk in doc["checks"]}

    # Reconcile: adopt any checklist Core already holds for a requirement the
    # doc doesn't know about (e.g. a publish run that crashed before the doc
    # write). Keyed by the crux_requirement_external_id property we stamp.
    existing_by_ext = fetch_published_by_external(c)

    published: list[tuple[str, str]] = []
    for req in sorted(catalog.requirements.values(), key=lambda r: r.external_id):
        if args.only and req.external_id != args.only:
            continue
        chk = checks_by_req.get(req.id)
        if chk is None:
            continue
        existing_rid = chk["publish"].get("checklistRid") or existing_by_ext.get(req.external_id)
        if existing_rid:
            current = c.checklist.get(c.auth_header, existing_rid)
            c.checklist.commit(
                c.auth_header,
                existing_rid,
                CommitChecklistRequest(
                    commit_message=f'Update "{req.external_id}" check from Crux Lite',
                    checks=[
                        UpdateChecklistEntryRequest(
                            create_check=check_entry(req.external_id, req.title, chk["tree"])
                        )
                    ],
                    checklist_variables=[],
                    latest_commit=current.commit.id,
                ),
            )
            rid = existing_rid
            action = "updated"
        else:
            created = c.checklist.create(
                c.auth_header,
                CreateChecklistRequest(
                    commit_message=f'Publish "{req.external_id}" check from Crux Lite',
                    assignee_rid=me.rid,
                    title=f"{req.external_id} — {req.title}",
                    description=f"Authored in Crux Lite for requirement {req.external_id}.",
                    checks=[
                        CreateChecklistEntryRequest(
                            create_check=check_entry(req.external_id, req.title, chk["tree"])
                        )
                    ],
                    properties={
                        "source": "crux-lite",
                        "crux_requirement_id": req.id,
                        "crux_requirement_external_id": req.external_id,
                        "crux_pass_criterion": chk.get("passCriterion", "no_violations"),
                        "verification_campaign": "rtx-uav",
                    },
                    labels=["verification", "crux"],
                    checklist_variables=[],
                    workspace=WORKSPACE_RID,
                ),
            )
            rid = created.rid
            action = "created"
        chk["publish"] = {"state": "published", "checklistRid": rid, "publishedAt": now_iso()}
        published.append((req.external_id, rid))
        print(f"{action}  {req.external_id}: {rid}")

    if published:
        revision = save_doc(manifest_entry, doc)
        print(f"\nCrux doc publish-state updated (revision {revision}); {len(published)} checklists.")


if __name__ == "__main__":
    main()
