"""Read/write Crux Lite's ProjectDoc through the Nova per-app key-value store.

Python port of the app's own store layer (labs apps/crux-lite/src/store/):

- ``nova-kv-store.ts``: routes are ``{APP_ORIGIN}/api/nova/v1/apps/<appRid>/kv``;
  keys admit RFC 3986 unreserved chars only, so the codec's ``/`` separators
  become ``.`` on the wire, prefixed ``cruxlite.<projectId>.``.
- ``chunk-codec.ts``: the doc is stored as a manifest
  ``{schemaRevision, revision, chunkKeys}`` plus per-field chunks keyed
  ``<field>/<revision>/<index>``. Array fields are JSON arrays split across
  chunks; ``settings`` is the one scalar field. 9 KiB raw budget per chunk.
- Save protocol: chunks are revision-fresh CREATEs; the manifest is the one
  key that updates in place, guarded by ``expectedVersion`` — a version
  conflict means someone else (usually an open app tab) saved concurrently.

WRITE WARNING: writing while a user has the app open makes THEIR next save a
conflict, which freezes their tab until they discard-and-reload. Seed-time
writes only; never write the doc mid-demo.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from staging_env import APP_ORIGIN, CRUX_APP_RID, CRUX_PROJECT_ID, token

ARRAY_FIELDS = [
    "types",
    "objects",
    "links",
    "changelog",
    "comments",
    "runExclusions",
    "manualVerdicts",
    "runAssignments",
    "checks",
    "variables",
    "views",
    "columnLayouts",
]
SCALAR_FIELDS = ["settings"]
CHUNK_BUDGET_BYTES = 9 * 1024
MAX_BATCH_ITEMS = 256


class KvConflict(RuntimeError):
    """Another writer changed the document — reload and retry."""


def _request(method: str, route: str, body: dict | None = None) -> Any:
    url = f"{APP_ORIGIN}/api/nova/v1/apps/{urllib.parse.quote(CRUX_APP_RID, safe='')}{route}"
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "content-type": "application/json",
            "accept": "application/json",
        },
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:400]
        if err.code in (409, 412) or "VersionConflict" in detail or "AlreadyExists" in detail:
            raise KvConflict(f"{method} {route}: {detail}") from err
        raise RuntimeError(f"KV {method} {route} failed: HTTP {err.code} {detail}") from err


def _storage_key(codec_key: str) -> str:
    return f"cruxlite.{CRUX_PROJECT_ID}." + codec_key.replace("/", ".")


def _manifest_key() -> str:
    return _storage_key("manifest")


def load_doc() -> tuple[dict, dict]:
    """Return (manifest_entry, doc). manifest_entry carries the KV version
    needed to write the doc back (see save_doc)."""
    entry = _request("GET", "/kv/" + urllib.parse.quote(_manifest_key(), safe=""))
    kv_entry = entry["keyValueEntry"]
    manifest = json.loads(kv_entry["value"])
    storage_keys = [_storage_key(k) for k in manifest["chunkKeys"]]
    values: dict[str, str] = {}
    for i in range(0, len(storage_keys), MAX_BATCH_ITEMS):
        page = _request("POST", "/kv/batch-get", {"keys": storage_keys[i : i + MAX_BATCH_ITEMS]})
        for e in page.get("keyValueEntries", []):
            values[e["key"]] = e["value"]

    doc: dict[str, Any] = {field: [] for field in ARRAY_FIELDS}
    for codec_key in sorted(
        manifest["chunkKeys"], key=lambda k: (k.split("/")[0], int(k.split("/")[2]))
    ):
        field = codec_key.split("/")[0]
        raw = values[_storage_key(codec_key)]
        if field in SCALAR_FIELDS:
            doc[field] = json.loads(raw)
        else:
            doc[field].extend(json.loads(raw))
    return {"version": kv_entry.get("version"), "manifest": manifest}, doc


def _pack_array_chunks(items: list) -> list[str]:
    payloads: list[str] = []
    bucket: list[str] = []
    bucket_bytes = 0
    for item in items:
        serialized = json.dumps(item, separators=(",", ":"), ensure_ascii=False)
        size = len(serialized.encode())
        if size + 2 > CHUNK_BUDGET_BYTES:
            raise ValueError(f"item too large to chunk ({size} bytes)")
        # Conservative: flush well under the raw budget so the stored (escaped)
        # form also clears the 10 KiB KV value cap the codec accounts exactly.
        if bucket and bucket_bytes + size + len(bucket) + 2 > CHUNK_BUDGET_BYTES - 1024:
            payloads.append("[" + ",".join(bucket) + "]")
            bucket, bucket_bytes = [], 0
        bucket.append(serialized)
        bucket_bytes += size
    if bucket:
        payloads.append("[" + ",".join(bucket) + "]")
    return payloads


def save_doc(manifest_entry: dict, doc: dict) -> str:
    """Write the doc back: create revision-fresh chunks, update the manifest
    with the version captured at load, then delete the superseded chunks.
    Raises KvConflict if the app (or anyone) saved since load_doc()."""
    revision = str(uuid.uuid4())
    chunks: dict[str, str] = {}
    for field in ARRAY_FIELDS:
        for idx, payload in enumerate(_pack_array_chunks(doc[field])):
            chunks[f"{field}/{revision}/{idx}"] = payload
    for field in SCALAR_FIELDS:
        chunks[f"{field}/{revision}/0"] = json.dumps(
            doc[field], separators=(",", ":"), ensure_ascii=False
        )

    writes = [{"key": _storage_key(k), "value": v} for k, v in chunks.items()]
    for i in range(0, len(writes), MAX_BATCH_ITEMS):
        _request("POST", "/kv/batch-create", {"writes": writes[i : i + MAX_BATCH_ITEMS]})

    new_manifest = {
        "schemaRevision": 1,
        "revision": revision,
        "chunkKeys": list(chunks.keys()),
    }
    version = manifest_entry["version"]
    expected = int(version) if isinstance(version, str) else version
    try:
        _request(
            "PUT",
            "/kv/" + urllib.parse.quote(_manifest_key(), safe=""),
            {"value": json.dumps(new_manifest, separators=(",", ":")), "expectedVersion": expected},
        )
    except KvConflict:
        # Our chunks are orphans now — reclaim them before surfacing.
        doomed = [w["key"] for w in writes]
        for i in range(0, len(doomed), MAX_BATCH_ITEMS):
            _request("POST", "/kv/batch-delete", {"keys": doomed[i : i + MAX_BATCH_ITEMS]})
        raise

    superseded = [_storage_key(k) for k in manifest_entry["manifest"]["chunkKeys"]]
    for i in range(0, len(superseded), MAX_BATCH_ITEMS):
        _request("POST", "/kv/batch-delete", {"keys": superseded[i : i + MAX_BATCH_ITEMS]})
    return revision
