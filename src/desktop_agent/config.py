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
    screenshot_archive_dir: str = "./runs/screenshots"
    log_path: str = "./runs/session.log"
    llm_trace_enabled: bool = True
    llm_trace_dir: str = "./runs/llm_traces"
    image_format: str = "jpeg"
    image_max_long_edge: int = 1280
    image_jpeg_quality: int = 70
    guard_exact_repeat_threshold: int = 5
    guard_semantic_repeat_threshold: int = 4
    guard_phase_stagnant_threshold: int = 1000000
    guard_type_text_focus: bool = True


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
        screenshot_archive_dir=str(runtime_data.get("screenshot_archive_dir", "./runs/screenshots")),
        log_path=str(runtime_data.get("log_path", "./runs/session.log")),
        llm_trace_enabled=bool(runtime_data.get("llm_trace_enabled", True)),
        llm_trace_dir=str(runtime_data.get("llm_trace_dir", "./runs/llm_traces")),
        image_format=str(runtime_data.get("image_format", "jpeg")).lower(),
        image_max_long_edge=int(runtime_data.get("image_max_long_edge", 1280)),
        image_jpeg_quality=int(runtime_data.get("image_jpeg_quality", 70)),
        guard_exact_repeat_threshold=int(runtime_data.get("guard_exact_repeat_threshold", 5)),
        guard_semantic_repeat_threshold=int(runtime_data.get("guard_semantic_repeat_threshold", 4)),
        guard_phase_stagnant_threshold=int(runtime_data.get("guard_phase_stagnant_threshold", 1000000)),
        guard_type_text_focus=bool(runtime_data.get("guard_type_text_focus", True)),
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
    if runtime_cfg.image_format not in {"jpeg", "png"}:
        raise ValueError("runtime.image_format must be one of: jpeg, png")
    if runtime_cfg.image_max_long_edge <= 0:
        raise ValueError("runtime.image_max_long_edge must be > 0")
    if not runtime_cfg.screenshot_archive_dir:
        raise ValueError("runtime.screenshot_archive_dir cannot be empty")
    if runtime_cfg.llm_trace_enabled and not runtime_cfg.llm_trace_dir:
        raise ValueError("runtime.llm_trace_dir cannot be empty when llm_trace_enabled=true")
    if not 1 <= runtime_cfg.image_jpeg_quality <= 95:
        raise ValueError("runtime.image_jpeg_quality must be in [1,95]")
    if runtime_cfg.guard_exact_repeat_threshold < 2:
        raise ValueError("runtime.guard_exact_repeat_threshold must be >= 2")
    if runtime_cfg.guard_semantic_repeat_threshold < 2:
        raise ValueError("runtime.guard_semantic_repeat_threshold must be >= 2")
    if runtime_cfg.guard_phase_stagnant_threshold < 0:
        raise ValueError("runtime.guard_phase_stagnant_threshold must be >= 0")

    return AppConfig(
        openai=openai_cfg,
        runtime=runtime_cfg,
        safety=safety_cfg,
        display=display_cfg,
    )
