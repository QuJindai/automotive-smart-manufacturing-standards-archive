from __future__ import annotations

from pathlib import Path
from typing import Any
from paas_ref.sample import SampleBundle
from paas_ref.rules import check_asset_kind, check_asset_identifier, check_required_semantics
from paas_ref.semantic import check_iec61360, check_languages, check_units, check_unit_resolvability


def _ref_value(ref: dict | None) -> str | None:
    if not isinstance(ref, dict): return None
    keys=ref.get("keys") or []
    if not keys or not isinstance(keys[0], dict): return None
    v=keys[0].get("value")
    return v if isinstance(v,str) and v else None


def _semantic_dictionary(environment: dict[str, Any]) -> dict[str, Any]:
    units: dict[str, dict[str, str]] = {}
    for cd in environment.get("conceptDescriptions", []):
        for spec in cd.get("embeddedDataSpecifications") or []:
            content=spec.get("dataSpecificationContent") if isinstance(spec,dict) else None
            if not isinstance(content,dict): continue
            uid=_ref_value(content.get("unitId"))
            unit=content.get("unit")
            if uid and isinstance(unit,str): units[uid]={"unit":unit}
    return {"units":units}


def normalize_bundle(environment: dict[str, Any], capabilities: dict[str, Any]) -> SampleBundle:
    return SampleBundle(root=Path("."), environment=environment, capabilities=capabilities, semantic_dictionary=_semantic_dictionary(environment))


def run_core_semantic_checks(sample: SampleBundle):
    return [check_asset_kind(sample), check_asset_identifier(sample), check_required_semantics(sample), check_iec61360(sample), check_languages(sample,{"en"}), check_units(sample), check_unit_resolvability(sample)]
