from __future__ import annotations

from collections import deque
from typing import Any


def _node(node_id: str, node_type: str, **attrs: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, **attrs}


def build_trace_graph(package: dict[str, Any]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str, str]] = set()

    def add_node(node_id: str, node_type: str, **attrs: Any) -> None:
        if node_id:
            nodes.setdefault(node_id, _node(node_id, node_type, **attrs))

    def add_edge(source: str, target: str, edge_type: str) -> None:
        if source and target:
            edges.add((source, target, edge_type))

    for record in package.get("records") or []:
        evidence_id = str(record.get("evidence_id") or "")
        add_node(evidence_id, "evidence", decision=(record.get("disposition") or {}).get("decision"))

        subject = record.get("subject") or {}
        subject_id = str(subject.get("subject_id") or "")
        add_node(subject_id, "subject", subject_type=subject.get("subject_type"), operation_id=subject.get("operation_id"))
        add_edge(evidence_id, subject_id, "SUBJECT_OF")

        source = record.get("source") or {}
        source_id = str(source.get("source_record_id") or "")
        if source_id:
            source_node_id = "source:" + source_id
            add_node(source_node_id, "source_record", system_id=source.get("system_id"))
            add_edge(evidence_id, source_node_id, "GENERATED_BY")

        equipment_id = str((record.get("process_context") or {}).get("equipment_id") or source.get("equipment_id") or "")
        add_node(equipment_id, "equipment")
        add_edge(evidence_id, equipment_id, "GENERATED_BY")

        execution = record.get("execution_context") or {}
        program_id = str(execution.get("program_id") or "")
        if program_id:
            program_node = f"program:{program_id}@{execution.get('program_version','')}"
            add_node(program_node, "program", program_id=program_id, version=execution.get("program_version"))
            add_edge(evidence_id, program_node, "USES_PROGRAM")
        parameter_id = str(execution.get("parameter_set_id") or "")
        if parameter_id:
            parameter_node = f"parameter:{parameter_id}@{execution.get('parameter_hash','')}"
            add_node(parameter_node, "parameter_set", parameter_set_id=parameter_id, sha256=execution.get("parameter_hash"))
            add_edge(evidence_id, parameter_node, "USES_PARAMETER_SET")

        for artifact in record.get("raw_artifacts") or []:
            artifact_id = str(artifact.get("artifact_id") or artifact.get("uri") or "")
            artifact_node = "artifact:" + artifact_id if artifact_id else ""
            add_node(artifact_node, "raw_artifact", uri=artifact.get("uri"), sha256=artifact.get("sha256"))
            add_edge(evidence_id, artifact_node, "HAS_RAW_ARTIFACT")

        lineage = record.get("lineage") or {}
        relation = str(lineage.get("relation") or "")
        for parent_id in lineage.get("parent_evidence_ids") or []:
            parent_id = str(parent_id)
            add_edge(evidence_id, parent_id, "DERIVED_FROM")
            if relation in {"RETEST_OF", "REPAIR_OF", "RELEASES"}:
                add_edge(evidence_id, parent_id, relation)

    return {
        "schema_version": "1.0",
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [{"source": s, "target": t, "type": typ} for s, t, typ in sorted(edges, key=lambda x: (x[0], x[2], x[1]))],
    }


def trace_release(graph: dict[str, Any], release_evidence_id: str) -> dict[str, Any]:
    outgoing: dict[str, list[dict[str, Any]]] = {}
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    for edge in graph.get("edges") or []:
        outgoing.setdefault(edge["source"], []).append(edge)

    visited_evidence: set[str] = set()
    queue: deque[str] = deque([release_evidence_id])
    selected_edges: list[dict[str, Any]] = []
    related_nodes: set[str] = {release_evidence_id}
    while queue:
        current = queue.popleft()
        if current in visited_evidence:
            continue
        visited_evidence.add(current)
        for edge in outgoing.get(current, []):
            selected_edges.append(edge)
            related_nodes.add(edge["target"])
            if edge["type"] == "DERIVED_FROM" and nodes.get(edge["target"], {}).get("type") == "evidence":
                queue.append(edge["target"])

    types = {nid: nodes.get(nid, {}).get("type") for nid in related_nodes}
    required_types = {"source_record", "equipment", "program", "parameter_set", "raw_artifact"}
    complete = bool(visited_evidence) and required_types.issubset(set(types.values()))
    return {
        "release_evidence_id": release_evidence_id,
        "complete": complete,
        "evidence_ids": sorted(visited_evidence),
        "source_records": sorted(n for n, typ in types.items() if typ == "source_record"),
        "equipment": sorted(n for n, typ in types.items() if typ == "equipment"),
        "programs": sorted(n for n, typ in types.items() if typ == "program"),
        "parameter_sets": sorted(n for n, typ in types.items() if typ == "parameter_set"),
        "artifacts": sorted(n for n, typ in types.items() if typ == "raw_artifact"),
        "edges": sorted(selected_edges, key=lambda e: (e["source"], e["type"], e["target"])),
    }
