from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


ALLOWED_ACTIONS = {
    "move",
    "click",
    "double_click",
    "right_click",
    "scroll",
    "type_text",
    "hotkey",
    "press",
    "wait",
    "finish",
}
ALLOWED_STATUS = {"in_progress", "completed", "blocked"}


@dataclass
class LLMAction:
    type: str
    payload: dict[str, Any]


@dataclass
class LLMDecision:
    thought: str
    status: str
    confidence: float
    reason_if_blocked: str
    action: LLMAction


def _as_float(v: Any, name: str) -> float:
    try:
        return float(v)
    except Exception as exc:
        raise ValueError(f"{name} must be numeric") from exc


def parse_decision(raw: str) -> LLMDecision:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Model output is not valid JSON") from exc

    if not isinstance(data, dict):
        raise ValueError("Model output must be a JSON object")

    thought = str(data.get("thought", "")).strip()
    status = str(data.get("status", "")).strip()
    confidence = _as_float(data.get("confidence", 0.0), "confidence")
    reason_if_blocked = str(data.get("reason_if_blocked", "")).strip()
    action = data.get("action")

    if status not in ALLOWED_STATUS:
        raise ValueError(f"Invalid status: {status}")
    if not isinstance(action, dict):
        raise ValueError("action must be an object")

    action_type = str(action.get("type", "")).strip()
    if action_type not in ALLOWED_ACTIONS:
        raise ValueError(f"Invalid action.type: {action_type}")

    if status == "blocked" and not reason_if_blocked:
        raise ValueError("reason_if_blocked is required when status=blocked")

    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be in [0,1]")

    payload = dict(action)
    payload.pop("type", None)
    return LLMDecision(
        thought=thought,
        status=status,
        confidence=confidence,
        reason_if_blocked=reason_if_blocked,
        action=LLMAction(type=action_type, payload=payload),
    )
