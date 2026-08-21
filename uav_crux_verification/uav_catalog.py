"""Load the Crux requirement catalog into the shapes the demo orchestrates.

The catalog is a DAG: `derived_from` links are stored child-first (source =
child requirement, target = parent), `verifies` links are test-case →
requirement. Crux Lite does NOT roll child-requirement status up to parents —
a requirement goes green only through its own test cases — so the
component → subsystem → system ordering here is orchestration policy, not a
Crux rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Requirement:
    id: str  # object id (uuid)
    external_id: str
    title: str
    level: str  # System | Subsystem | Component | ""
    test_case_ids: list[str] = field(default_factory=list)  # object ids
    child_ids: list[str] = field(default_factory=list)  # requirement object ids
    parent_ids: list[str] = field(default_factory=list)


@dataclass
class TestCase:
    id: str
    external_id: str
    title: str


@dataclass
class Catalog:
    requirements: dict[str, Requirement]  # by object id
    test_cases: dict[str, TestCase]  # by object id
    by_external: dict[str, Requirement]
    roots: list[Requirement]  # system-level trees (plus any stray roots)

    def tree_schedule(self, root: Requirement) -> list[Requirement]:
        """Bottom-up, depth-first order for one system tree: components,
        then their subsystem, ..., root last. Deterministic by external id."""
        ordered: list[Requirement] = []
        seen: set[str] = set()

        def visit(req: Requirement) -> None:
            if req.id in seen:
                return
            seen.add(req.id)
            for child_id in sorted(
                req.child_ids, key=lambda i: self.requirements[i].external_id
            ):
                visit(self.requirements[child_id])
            ordered.append(req)

        visit(root)
        return ordered


def load_catalog(doc: dict) -> Catalog:
    objects = {o["id"]: o for o in doc["objects"] if not o.get("archived")}
    requirements: dict[str, Requirement] = {}
    test_cases: dict[str, TestCase] = {}
    for oid, obj in objects.items():
        props = obj.get("properties") or {}
        if obj["typeId"] == "builtin-requirement":
            requirements[oid] = Requirement(
                id=oid,
                external_id=props.get("external_id", ""),
                title=props.get("title", ""),
                level=props.get("level", ""),
            )
        elif obj["typeId"] == "builtin-test-case":
            test_cases[oid] = TestCase(
                id=oid,
                external_id=props.get("external_id", ""),
                title=props.get("title", ""),
            )

    for link in doc["links"]:
        src, tgt = link["sourceId"], link["targetId"]
        if link["linkType"] == "derived_from" and src in requirements and tgt in requirements:
            requirements[tgt].child_ids.append(src)
            requirements[src].parent_ids.append(tgt)
        elif link["linkType"] == "verifies" and src in test_cases and tgt in requirements:
            requirements[tgt].test_case_ids.append(src)

    by_external = {r.external_id: r for r in requirements.values()}
    roots = sorted(
        (r for r in requirements.values() if not r.parent_ids),
        key=lambda r: r.external_id,
    )
    return Catalog(
        requirements=requirements, test_cases=test_cases, by_external=by_external, roots=roots
    )
