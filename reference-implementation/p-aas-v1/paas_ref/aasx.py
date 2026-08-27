from __future__ import annotations

import json
import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .rules import CheckResult
from .sample import SampleBundle

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
AASX_ORIGIN_REL = "http://admin-shell.io/aasx/relationships/aasx-origin"
AAS_SPEC_REL = "http://admin-shell.io/aasx/relationships/aas-spec"
AAS_SUPPL_REL = "http://admin-shell.io/aasx/relationships/aas-suppl"


def _rels_xml(rows: list[tuple[str, str, str]]) -> bytes:
    root = ET.Element(f"{{{REL_NS}}}Relationships")
    for rel_id, rel_type, target in rows:
        ET.SubElement(root, f"{{{REL_NS}}}Relationship", Id=rel_id, Type=rel_type, Target=target)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _content_types_xml() -> bytes:
    root = ET.Element(f"{{{CT_NS}}}Types")
    ET.SubElement(root, f"{{{CT_NS}}}Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    ET.SubElement(root, f"{{{CT_NS}}}Default", Extension="json", ContentType="application/json")
    ET.SubElement(root, f"{{{CT_NS}}}Default", Extension="txt", ContentType="text/plain")
    ET.SubElement(root, f"{{{CT_NS}}}Override", PartName="/aasx/aasx-origin", ContentType="application/aas-origin")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_aasx(sample: SampleBundle, destination: str | Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    supplementary = sorted(p for p in sample.supplementary_dir.iterdir() if p.is_file())
    env_rels = [(f"R{i+1}", AAS_SUPPL_REL, f"suppl/{p.name}") for i, p in enumerate(supplementary)]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _content_types_xml())
        z.writestr("_rels/.rels", _rels_xml([("R1", AASX_ORIGIN_REL, "/aasx/aasx-origin")]))
        z.writestr("aasx/aasx-origin", b"")
        z.writestr("aasx/_rels/aasx-origin.rels", _rels_xml([("R1", AAS_SPEC_REL, "aas-environment.json")]))
        z.writestr("aasx/aas-environment.json", json.dumps(sample.environment, ensure_ascii=False, indent=2).encode("utf-8"))
        z.writestr("aasx/_rels/aas-environment.json.rels", _rels_xml(env_rels))
        for p in supplementary:
            z.write(p, f"aasx/suppl/{p.name}")
    return destination


def _relationship_targets(z: zipfile.ZipFile, rel_path: str, source_part: str) -> list[tuple[str, str]]:
    root = ET.fromstring(z.read(rel_path))
    base = posixpath.dirname(source_part)
    rows = []
    for rel in root.findall(f"{{{REL_NS}}}Relationship"):
        target = rel.attrib.get("Target", "")
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))
        rows.append((rel.attrib.get("Type", ""), resolved))
    return rows


def _relationships_path_for_part(source_part: str) -> str:
    directory = posixpath.dirname(source_part)
    filename = posixpath.basename(source_part)
    return posixpath.join(directory, "_rels", filename + ".rels")


def validate_aasx(path: str | Path, required_supplementary: set[str]) -> list[CheckResult]:
    path = Path(path)
    results: list[CheckResult] = []
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            required_core = {"[Content_Types].xml", "_rels/.rels", "aasx/aasx-origin", "aasx/_rels/aasx-origin.rels"}
            missing_core = sorted(required_core - names)
            results.append(CheckResult("aasx-core", not missing_core, "core OPC/AASX parts present" if not missing_core else f"missing core parts: {missing_core}", missing_core))
            results.append(CheckResult("aasx-origin", "aasx/aasx-origin" in names, "aasx-origin present" if "aasx/aasx-origin" in names else "aasx-origin missing", None))
            if "_rels/.rels" in names:
                root_targets = _relationship_targets(z, "_rels/.rels", "")
                origin_targets = [target for typ, target in root_targets if typ == AASX_ORIGIN_REL]
                ok = origin_targets == ["aasx/aasx-origin"] and all(t in names for t in origin_targets)
                results.append(CheckResult("aasx-origin-relationship", ok, f"origin relationship targets={origin_targets}", origin_targets))
            else:
                results.append(CheckResult("aasx-origin-relationship", False, "root relationship file missing", None))

            spec_targets: list[str] = []
            if "aasx/_rels/aasx-origin.rels" in names:
                origin_rels = _relationship_targets(z, "aasx/_rels/aasx-origin.rels", "aasx/aasx-origin")
                spec_targets = [target for typ, target in origin_rels if typ == AAS_SPEC_REL]
                missing_spec_targets = sorted(t for t in spec_targets if t not in names)
                ok = bool(spec_targets) and not missing_spec_targets
                message = f"AAS environment targets={spec_targets}" if ok else f"AAS environment targets={spec_targets}, missing={missing_spec_targets}"
                results.append(CheckResult("aasx-spec-relationship", ok, message, spec_targets))
            else:
                results.append(CheckResult("aasx-spec-relationship", False, "aasx-origin relationships missing", None))

            linked: set[str] = set()
            for spec_part in spec_targets:
                rel_path = _relationships_path_for_part(spec_part)
                if rel_path not in names:
                    continue
                for typ, target in _relationship_targets(z, rel_path, spec_part):
                    if typ == AAS_SUPPL_REL and target in names:
                        linked.add(posixpath.basename(target))
            package_files = {posixpath.basename(name) for name in names if not name.endswith("/")}
            missing_files = sorted(required_supplementary - package_files)
            missing_links = sorted(required_supplementary - linked)
            ok = not missing_files and not missing_links
            results.append(CheckResult("aasx-supplementary", ok, "supplementary files present and linked" if ok else f"missing files={missing_files}, missing links={missing_links}", {"linked": sorted(linked)}))
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        results.append(CheckResult("aasx-package", False, f"cannot validate package: {exc}", None))
    return results
