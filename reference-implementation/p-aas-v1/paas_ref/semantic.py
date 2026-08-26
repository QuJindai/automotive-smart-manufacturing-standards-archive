from __future__ import annotations

from .rules import CheckResult
from .sample import SampleBundle


def _content(cd: dict) -> dict | None:
    specs = cd.get("embeddedDataSpecifications") or []
    for spec in specs:
        content = spec.get("dataSpecificationContent") if isinstance(spec, dict) else None
        if isinstance(content, dict) and content.get("modelType") == "DataSpecificationIec61360":
            return content
    return None


def _unit_id(content: dict) -> str | None:
    unit_id = content.get("unitId")
    if not isinstance(unit_id, dict):
        return None
    keys = unit_id.get("keys") or []
    if not keys:
        return None
    value = keys[0].get("value") if isinstance(keys[0], dict) else None
    return value if isinstance(value, str) and value else None


def check_iec61360(sample: SampleBundle) -> CheckResult:
    missing = [cd.get("idShort", cd.get("id", "<concept>")) for cd in sample.environment.get("conceptDescriptions", []) if _content(cd) is None]
    passed = not missing
    return CheckResult("iec61360", passed, "all ConceptDescriptions include IEC61360-style content" if passed else f"missing IEC61360 content: {', '.join(missing)}", missing)


def check_languages(sample: SampleBundle, required_languages: set[str]) -> CheckResult:
    missing: dict[str, list[str]] = {}
    for cd in sample.environment.get("conceptDescriptions", []):
        content = _content(cd)
        if content is None:
            missing[cd.get("idShort", "<concept>")] = sorted(required_languages)
            continue
        present = {item.get("language") for item in content.get("preferredName", []) if isinstance(item, dict)}
        absent = sorted(required_languages - present)
        if absent:
            missing[cd.get("idShort", "<concept>")] = absent
    passed = not missing
    return CheckResult("preferred-languages", passed, "required preferredName languages present" if passed else f"missing preferredName languages: {missing}", missing)


def check_units(sample: SampleBundle) -> CheckResult:
    mismatches: list[str] = []
    units = sample.semantic_dictionary.get("units", {})
    for cd in sample.environment.get("conceptDescriptions", []):
        content = _content(cd)
        if content is None:
            continue
        unit = content.get("unit")
        uid = _unit_id(content)
        if unit is None and uid is None:
            continue
        if unit is None or uid is None:
            mismatches.append(f"{cd.get('idShort')}: unit/unitId pair incomplete")
            continue
        mapped = units.get(uid)
        if mapped is None or mapped.get("unit") != unit:
            mismatches.append(f"{cd.get('idShort')}: {unit!r} != mapping for {uid!r}")
    passed = not mismatches
    return CheckResult("unit-consistency", passed, "unit and unitId mappings are consistent" if passed else "; ".join(mismatches), mismatches)


def check_unit_resolvability(sample: SampleBundle) -> CheckResult:
    unknown: list[str] = []
    units = sample.semantic_dictionary.get("units", {})
    for cd in sample.environment.get("conceptDescriptions", []):
        content = _content(cd)
        if content is None:
            continue
        uid = _unit_id(content)
        if uid is not None and uid not in units:
            unknown.append(uid)
    passed = not unknown
    return CheckResult("unit-resolvability", passed, "all unitIds resolve" if passed else f"unknown unitIds: {unknown}", unknown)
