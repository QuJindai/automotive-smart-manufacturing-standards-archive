from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from paas_ref.aasx import build_aasx
from paas_ref.sample import SampleBundle

SUPPLEMENTARY_FILES = {
    "manual.txt": "Synthetic EOL station operating manual for interoperability testing.\n",
    "program-version-note.txt": "Synthetic program EOL_REFERENCE version 1.0.0.\n",
    "certificate.txt": "Synthetic conformity evidence certificate placeholder.\n",
}

FILE_ELEMENTS = [
    ("OperatingManual", "manual.txt", "urn:example:automotive:concept:operating-manual"),
    ("ProgramVersionNote", "program-version-note.txt", "urn:example:automotive:concept:program-version-note"),
    ("ConformityCertificate", "certificate.txt", "urn:example:automotive:concept:conformity-certificate"),
]


def _file_element(id_short: str, filename: str, semantic_id: str) -> dict[str, Any]:
    return {
        "modelType": "File",
        "idShort": id_short,
        "semanticId": {
            "type": "ExternalReference",
            "keys": [{"type": "GlobalReference", "value": semantic_id}],
        },
        "contentType": "text/plain",
        "value": f"/aasx/suppl/{filename}",
    }


def build_supplementary_aasx(environment: dict[str, Any], work_dir: str | Path) -> tuple[dict[str, Any], Path, set[str]]:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    supplementary_dir = work_dir / "supplementary"
    supplementary_dir.mkdir(parents=True, exist_ok=True)

    enriched = deepcopy(environment)
    try:
        documentation = next(sm for sm in enriched.get("submodels", []) if sm.get("idShort") == "Documentation")
    except StopIteration as exc:
        raise ValueError("fixture has no Documentation Submodel") from exc
    elements = documentation.setdefault("submodelElements", [])
    existing = {element.get("idShort") for element in elements}
    for id_short, filename, semantic_id in FILE_ELEMENTS:
        if id_short not in existing:
            elements.append(_file_element(id_short, filename, semantic_id))

    for filename, content in SUPPLEMENTARY_FILES.items():
        (supplementary_dir / filename).write_text(content, encoding="utf-8")

    sample = SampleBundle(
        root=work_dir,
        environment=enriched,
        capabilities={"capabilities": []},
        semantic_dictionary={"units": {}},
    )
    package = build_aasx(sample, work_dir / "supplementary-input.aasx")
    return enriched, package, set(SUPPLEMENTARY_FILES)
