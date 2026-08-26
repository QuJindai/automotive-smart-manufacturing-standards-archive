from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED_ENV_KEYS = {"assetAdministrationShells", "submodels", "conceptDescriptions"}


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load JSON fixture {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"fixture {path} must contain a JSON object")
    return value


@dataclass(frozen=True)
class SampleBundle:
    root: Path
    environment: dict
    capabilities: dict
    semantic_dictionary: dict

    @property
    def aas(self) -> dict:
        shells = self.environment["assetAdministrationShells"]
        if not shells:
            raise ValueError("sample has no AssetAdministrationShell")
        return shells[0]

    @property
    def aas_id(self) -> str:
        return self.aas["id"]

    @property
    def submodel_ids(self) -> dict[str, str]:
        return {item["idShort"]: item["id"] for item in self.environment["submodels"]}

    @property
    def supplementary_dir(self) -> Path:
        return self.root / "supplementary"


def load_sample(root: str | Path) -> SampleBundle:
    root = Path(root)
    environment = _load_json(root / "aas-environment.json")
    capabilities = _load_json(root / "capabilities.json")
    semantic_dictionary = _load_json(root / "semantic-dictionary.json")
    missing = REQUIRED_ENV_KEYS - set(environment)
    if missing:
        raise ValueError(f"AAS environment missing keys: {sorted(missing)}")
    if not isinstance(environment["assetAdministrationShells"], list) or not isinstance(environment["submodels"], list):
        raise ValueError("AAS environment shell/submodel collections must be arrays")
    if "capabilities" not in capabilities or not isinstance(capabilities["capabilities"], list):
        raise ValueError("capabilities.json must contain a capabilities array")
    if "units" not in semantic_dictionary or not isinstance(semantic_dictionary["units"], dict):
        raise ValueError("semantic-dictionary.json must contain a units object")
    bundle = SampleBundle(root=root, environment=environment, capabilities=capabilities, semantic_dictionary=semantic_dictionary)
    _ = bundle.aas_id
    return bundle
