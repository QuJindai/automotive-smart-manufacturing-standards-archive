from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .sample import SampleBundle


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    passed: bool
    message: str
    observed: Any = None


def _ref_value(ref: dict | None) -> str | None:
    if not ref or not isinstance(ref, dict):
        return None
    keys = ref.get("keys") or []
    if not keys or not isinstance(keys[0], dict):
        return None
    value = keys[0].get("value")
    return value if isinstance(value, str) and value else None


def check_asset_kind(sample: SampleBundle) -> CheckResult:
    kind = sample.aas.get("assetInformation", {}).get("assetKind")
    return CheckResult("asset-kind", kind in {"Type", "Instance"}, f"assetKind={kind!r}", kind)


def check_asset_identifier(sample: SampleBundle) -> CheckResult:
    info = sample.aas.get("assetInformation", {})
    global_id = info.get("globalAssetId")
    specific = info.get("specificAssetIds") or []
    passed = bool(global_id) or bool(specific)
    return CheckResult("asset-identifier", passed, "asset identifier present" if passed else "missing globalAssetId and specificAssetIds", {"globalAssetId": global_id, "specificAssetIds": specific})


def check_required_semantics(sample: SampleBundle) -> CheckResult:
    missing: list[str] = []
    for submodel in sample.environment.get("submodels", []):
        if not _ref_value(submodel.get("semanticId")):
            missing.append(submodel.get("idShort", submodel.get("id", "<submodel>")))
        for element in submodel.get("submodelElements", []):
            if not _ref_value(element.get("semanticId")):
                missing.append(element.get("idShort", "<element>"))
    passed = not missing
    return CheckResult("required-semantics", passed, "all required semanticId values present" if passed else f"missing semanticId: {', '.join(missing)}", missing)


def check_capabilities(sample: SampleBundle, required: set[str]) -> CheckResult:
    declared = set(sample.capabilities.get("capabilities", []))
    missing = sorted(required - declared)
    passed = not missing
    return CheckResult("capabilities", passed, "required capabilities declared" if passed else f"missing capabilities: {', '.join(missing)}", {"declared": sorted(declared), "missing": missing})
