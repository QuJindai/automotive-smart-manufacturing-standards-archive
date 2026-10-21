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


def validate_supplementary_roundtrip(fixture: dict[str, Any], imported: bytes, exported: Path):
    """Verify logical File identities, OPC links and bytes across package renaming."""
    import hashlib
    import io
    import json
    import posixpath
    import zipfile
    from xml.etree import ElementTree as ET
    from paas_ref.aasx import AAS_SPEC_REL, AAS_SUPPL_REL, _relationship_targets, _relationships_path_for_part
    from paas_ref.rules import CheckResult

    def json_files(environment):
        files = {}
        def walk(elements, key):
            for element in elements or []:
                identity = key + (element.get('idShort', ''),)
                if element.get('modelType') == 'File':
                    if identity in files: raise ValueError('duplicate File identity')
                    files[identity] = element.get('value', '')
                children = element.get('value')
                walk(children if isinstance(children, list) else element.get('submodelElements'), identity)
        for submodel in environment.get('submodels', []):
            walk(submodel.get('submodelElements'), (submodel['id'],))
        return files

    def xml_files(payload):
        root = ET.fromstring(payload)
        files = {}
        def walk(node, key):
            identity = key
            short = node.find('{*}idShort')
            if short is not None: identity += (short.text or '',)
            if node.tag.rsplit('}', 1)[-1] == 'file':
                if identity in files: raise ValueError('duplicate File identity')
                files[identity] = node.findtext('{*}value', '')
            for child in node:
                if child.tag.rsplit('}', 1)[-1] not in {'idShort', 'id'}: walk(child, identity)
        for submodel in root.findall('./{*}submodels/{*}submodel'):
            for element in submodel.findall('./{*}submodelElements/*'):
                walk(element, (submodel.findtext('{*}id', ''),))
        return files

    verified = []
    failures = []
    try:
        with zipfile.ZipFile(io.BytesIO(imported)) as source, zipfile.ZipFile(exported) as target:
            expected = json_files(fixture)
            actual = {}
            linked = set()
            for kind, part in _relationship_targets(target, 'aasx/_rels/aasx-origin.rels', 'aasx/aasx-origin'):
                if kind != AAS_SPEC_REL: continue
                content = target.read(part)
                rows = json_files(json.loads(content)) if part.endswith('.json') else xml_files(content)
                if actual.keys() & rows.keys(): raise ValueError('duplicate File identity across environment parts')
                actual.update(rows)
                rels = _relationships_path_for_part(part)
                for rel_kind, path in _relationship_targets(target, rels, part):
                    if rel_kind == AAS_SUPPL_REL: linked.add(path)
            for identity, original in expected.items():
                path = actual.get(identity, '').lstrip('/')
                if not path or path not in linked or path not in target.namelist():
                    failures.append('/'.join(identity) + ': missing File target or OPC link')
                    continue
                before = source.read(original.lstrip('/'))
                after = target.read(path)
                if before != after:
                    failures.append('/'.join(identity) + ': attachment bytes changed')
                    continue
                verified.append({'original': posixpath.basename(original), 'exported': path, 'sha256': hashlib.sha256(after).hexdigest()})
            if not expected: failures.append('No File references to verify')
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        failures.append(str(exc))
    return CheckResult('aasx-supplementary', not failures,
        '; '.join(failures) if failures else 'File identities, OPC links and SHA-256 preserved across package serialization',
        {'linked': sorted(posixpath.basename(row['exported']) for row in verified),
         'verified_originals': sorted(row['original'] for row in verified), 'files': verified})
