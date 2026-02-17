from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class OpenAIConfig:
    base_url: str
    api_key: str
    model: str
    timeout_sec: int = 60


@dataclass
class RuntimeConfig:
    max_steps: int = 40
    step_delay_sec: float = 0.4
    screenshot_path: str = "./runs/latest.png"
    log_path: str = "./runs/session.log"


@dataclass
class SafetyConfig:
    mode: str = "mixed"
    confirm_actions: list[str] | None = None


@dataclass
class DisplayConfig:
    monitor: str = "primary"
    coordinate_base: int = 1000


@dataclass
class AppConfig:
    openai: OpenAIConfig
    runtime: RuntimeConfig
    safety: SafetyConfig
    display: DisplayConfig


def _require(config: dict[str, Any], key: str) -> Any:
    value = config.get(key)
    if value is None or value == "":
        raise ValueError(f"Missing required config field: {key}")
    return value


def load_config(path: str) -> AppConfig:
    raw_text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw_text) or {}

    openai_data = data.get("openai", {})
    runtime_data = data.get("runtime", {})
    safety_data = data.get("safety", {})
    display_data = data.get("display", {})

    openai_cfg = OpenAIConfig(
        base_url=_require(openai_data, "base_url"),
        api_key=_require(openai_data, "api_key"),
        model=_require(openai_data, "model"),
        timeout_sec=int(openai_data.get("timeout_sec", 60)),
    )

    runtime_cfg = RuntimeConfig(
        max_steps=int(runtime_data.get("max_steps", 40)),
        step_delay_sec=float(runtime_data.get("step_delay_sec", 0.4)),
        screenshot_path=str(runtime_data.get("screenshot_path", "./runs/latest.png")),
        log_path=str(runtime_data.get("log_path", "./runs/session.log")),
    )

    safety_cfg = SafetyConfig(
        mode=str(safety_data.get("mode", "mixed")),
        confirm_actions=list(
            safety_data.get(
                "confirm_actions",
                ["type_text", "hotkey", "right_click", "double_click"],
            )
        ),
    )

    display_cfg = DisplayConfig(
        monitor=str(display_data.get("monitor", "primary")),
        coordinate_base=int(display_data.get("coordinate_base", 1000)),
    )

    if safety_cfg.mode not in {"mixed", "manual", "auto"}:
        raise ValueError("safety.mode must be one of: mixed, manual, auto")
    if display_cfg.coordinate_base <= 0:
        raise ValueError("display.coordinate_base must be > 0")
    if display_cfg.monitor != "primary":
        raise ValueError("Only display.monitor=primary is supported in this version")

    return AppConfig(
        openai=openai_cfg,
        runtime=runtime_cfg,
        safety=safety_cfg,
        display=display_cfg,
    )
