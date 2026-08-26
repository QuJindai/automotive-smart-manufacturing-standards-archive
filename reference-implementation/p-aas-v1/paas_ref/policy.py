from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason_code: str
    attributes: dict

def evaluate_abac(subject: dict, resource: dict, context: dict) -> Decision:
    attrs={"subject":dict(subject),"resource":dict(resource),"context":dict(context)}
    if subject.get("factory") != resource.get("factory"):
        return Decision(False,"FACTORY_MISMATCH",attrs)
    if subject.get("role") != "engineer":
        return Decision(False,"ROLE_DENIED",attrs)
    hour=context.get("hour")
    if not isinstance(hour,int) or not 6 <= hour < 22:
        return Decision(False,"OUTSIDE_TIME_WINDOW",attrs)
    if context.get("equipment_state") != "READY":
        return Decision(False,"EQUIPMENT_NOT_READY",attrs)
    return Decision(True,"ALLOW",attrs)
