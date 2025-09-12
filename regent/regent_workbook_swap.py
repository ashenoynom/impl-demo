#!/usr/bin/env python3
import sys
import argparse
import csv
import json
from copy import deepcopy
from typing import Any, Dict, Generator

from nominal import NominalClient
from nominal_api.scout_template_api import CreateTemplateRequest
from nominal.thirdparty.pandas import channel_to_dataframe_decimated, channel_to_series
from nominal_api.scout_compute_api import StringConstant

# =========================================================
# === HARDCODED DEBUG INPUTS (used if no CLI args given) ===
# =========================================================
DEBUG_API_KEY = "nominal_api_key_X63ZKY5CPUDWHOKC2FRX22K6KRHDSAMZRDEPEDT4FSQ4245WYICA_79563321"  # Replace with your staging key
DEBUG_NOTEBOOK_RID = "ri.scout.cerulean-staging.notebook.c6e5f992-042c-421d-a7af-dc2b6949a9c1"
DEBUG_MAPPING_CSV_PATH = "/Users/ashenoy/Code/impl-demo/regent/channel_mapping.csv"
DEBUG_NEW_REF_NAME = "dev_ref"
DEBUG_POST_TEMPLATE = True  # True = actually post, False = dry run

# =========================================================
# 1️⃣ Load channel mapping CSV
# =========================================================
def load_mapping_csv(mapping_csv_path: str) -> Dict[str, str]:
    """Load mapping CSV into dict {old_channel: new_channel}."""
    mapping = {}
    with open(mapping_csv_path, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            old_name = row["Display Name"].strip()
            new_name = row["New Name"].strip()
            mapping[old_name] = new_name
    return mapping

# =========================================================
# 2️⃣ Patch the AssetChannel leaf
# =========================================================
def patch_asset_channel(asset, mapping_dict, new_ref_name):
    """Patch a scout_compute_api_AssetChannel for Template conversion."""

    # 🔄 Channel replacement
    old_channel_literal = getattr(asset.channel, "literal", None)
    if old_channel_literal and old_channel_literal in mapping_dict:
        new_channel_name = mapping_dict[old_channel_literal]
        asset._channel = StringConstant(literal=new_channel_name)
        print(f"🔄 Mapping channel: {old_channel_literal} → {new_channel_name}")
    else:
        print(f"⚠️ Channel NOT mapped, leaving as-is: {old_channel_literal}")

    # 🔄 Data scope replacement
    if hasattr(asset.data_scope_name, "literal"):
        asset._data_scope_name = StringConstant(literal=new_ref_name)

    # 🔄 Convert asset_rid.literal → variable("asset_rid") for Template
    if hasattr(asset.asset_rid, "literal"):
        asset._asset_rid = StringConstant(variable="asset_rid")
        print(f"🔄 Converted asset_rid.literal → asset_rid.variable for Template")

# =========================================================
# 3️⃣ Generic extractor for nested ComputeNodes
# =========================================================
def extract_nested_nodes(series_obj: Any) -> Generator[Any, None, None]:
    """Yield nested ComputeNodes inside series_obj (list/dict/attrs)."""
    if series_obj is None:
        return
    for attr_name in dir(series_obj):
        if attr_name.startswith("_"):
            continue
        try:
            val = getattr(series_obj, attr_name)
        except Exception:
            continue
        # Single ComputeNode
        if hasattr(val, "numeric") or hasattr(val, "enum") or hasattr(val, "log"):
            yield val
        # List of nodes
        if isinstance(val, list):
            for item in val:
                if hasattr(item, "numeric") or hasattr(item, "enum") or hasattr(item, "log"):
                    yield item
        # Dict of nodes
        if isinstance(val, dict):
            for item in val.values():
                if hasattr(item, "numeric") or hasattr(item, "enum") or hasattr(item, "log"):
                    yield item

# =========================================================
# 4️⃣ Recursive traversal for ComputeNodes
# =========================================================
def visit_compute_node(node: Any, mapping: Dict[str, str], ref_name: str) -> None:
    """
    Recursively traverse a ComputeNode:
      - If it has a 'channel' directly, patch it.
      - Otherwise, check its active union (_type), get that nested value, and:
          * Patch its channel if present
          * Recurse into any nested ComputeNodes within it
    """

    if node is None:
        return

    # If the node itself has a channel → patch
    if hasattr(node, "channel") and node.channel is not None:
        if hasattr(node.channel, "asset"):
            patch_asset_channel(node.channel.asset, mapping, ref_name)

    # Detect which union field is active
    active_type = getattr(node, "_type", None)
    if not active_type:
        return  # No active union

    # Retrieve the actual nested object (enum/numeric/log/ranges/curve_fit/raw)
    nested = getattr(node, active_type, None)
    if nested is None:
        return

    # If that nested object has a channel → patch
    if hasattr(nested, "channel") and nested.channel is not None:
        if hasattr(nested.channel, "asset"):
            patch_asset_channel(nested.channel.asset, mapping, ref_name)

    # Now look deeper for any additional ComputeNodes inside lists/dicts/attrs
    for deeper_node in extract_nested_nodes(nested):
        visit_compute_node(deeper_node, mapping, ref_name)

    # Also recurse directly into the nested object
    visit_compute_node(nested, mapping, ref_name)

# =========================================================
# 5️⃣ Convert Notebook -> Template
# =========================================================
def convert_notebook_to_template_request(notebook_obj, mapping_dict, new_ref_name):
    """Convert Notebook → CreateTemplateRequest with patched channels, display_names, and robust title handling."""

    template_like = deepcopy(notebook_obj)

    # Patch every channel_variable
    for var_name, channel_var in template_like.content.channel_variables.items():
        compute_node = channel_var.compute_spec_v2.compute_node
        visit_compute_node(compute_node, mapping_dict, new_ref_name)

        # 🔄 Patch display_name if in mapping CSV
        old_display = channel_var.display_name
        if old_display in mapping_dict:
            new_display = mapping_dict[old_display]
            channel_var._display_name = new_display
            print(f"🔄 Updated display_name: {old_display} → {new_display}")
        else:
            print(f"⚠️ display_name NOT mapped, leaving as-is: {old_display}")

    # Pull Notebook metadata
    nb_meta = notebook_obj.metadata
    notebook_title = nb_meta.title.strip() if nb_meta.title else ""

    # If no title, prompt
    if not notebook_title:
        notebook_title = input("⚠️ Notebook title is empty. Please enter a Notebook name: ").strip()
        if not notebook_title:
            notebook_title = "Untitled Notebook"

    title = f"Template from {notebook_title} - Historical Flight Channel Conversion"
    description = f"Auto-generated from Notebook {notebook_obj.rid}"
    labels = nb_meta.labels or []
    properties = nb_meta.properties or {}
    message = f"Converted from Notebook {notebook_obj.rid}"

    return CreateTemplateRequest(
        title=title,
        description=description,
        labels=labels,
        properties=properties,
        message=message,
        layout=notebook_obj.layout,
        content=template_like.content
    )

# =========================================================
# 6️⃣ Main runner
# =========================================================
def run_conversion(api_key: str, notebook_rid: str, mapping_csv_path: str, new_ref_name: str, post_template: bool):
    """Core runner that works for both CLI and debug."""
    client = NominalClient.from_token(token=api_key)

    mapping_dict = load_mapping_csv(mapping_csv_path)
    print(f"✅ Loaded {len(mapping_dict)} channel mappings.")

    notebook = client._clients.notebook.get(auth_header=api_key, rid=notebook_rid)
    print(f"✅ Pulled Notebook: {notebook.metadata.title}")

    req = convert_notebook_to_template_request(notebook, mapping_dict, new_ref_name)
    print(f"✅ Built CreateTemplateRequest for: {req.title}")

    if post_template:
        created_template = client._clients.template.create(auth_header=api_key, request=req)
        print(f"✅ Posted new Template: {created_template.rid}")
    else:
        print("📝 Dry run only:")
        print(json.dumps(req.to_dict(), indent=2))

def main():
    parser = argparse.ArgumentParser(description="Convert Notebook -> Template")
    parser.add_argument("--api_key", help="Nominal API key")
    parser.add_argument("--notebook_rid", help="Notebook RID")
    parser.add_argument("--mapping_csv", help="Path to channel mapping CSV")
    parser.add_argument("--ref_name", help="New data_scope_name to set")
    parser.add_argument("--post", action="store_true", help="Actually post the Template")
    args = parser.parse_args()

    # If no CLI args → fall back to debug mode
    if len(sys.argv) == 1:
        print("▶️ Running in DEBUG mode (no CLI args provided)")
        run_conversion(
            api_key=DEBUG_API_KEY,
            notebook_rid=DEBUG_NOTEBOOK_RID,
            mapping_csv_path=DEBUG_MAPPING_CSV_PATH,
            new_ref_name=DEBUG_NEW_REF_NAME,
            post_template=DEBUG_POST_TEMPLATE
        )
    else:
        # CLI mode
        run_conversion(
            api_key=args.api_key,
            notebook_rid=args.notebook_rid,
            mapping_csv_path=args.mapping_csv,
            new_ref_name=args.ref_name,
            post_template=args.post
        )

if __name__ == "__main__":
    main()
