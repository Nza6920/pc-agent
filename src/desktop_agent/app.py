from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .actions import perform_action
from .config import AppConfig
from .llm import LLMClient
from .prompts import build_user_prompt
from .safety import confirm_action_cli, needs_confirmation
from .screen import capture_primary_png, get_primary_resolution, png_to_base64


def _append_log(path: str, item: dict) -> None:
    log_file = Path(path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _action_signature(action_type: str, payload: dict[str, Any]) -> str:
    return f"{action_type}:{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"


def run_agent(task: str, cfg: AppConfig) -> int:
    width, height = get_primary_resolution()
    llm = LLMClient(
        base_url=cfg.openai.base_url,
        api_key=cfg.openai.api_key,
        model=cfg.openai.model,
        timeout_sec=cfg.openai.timeout_sec,
    )

    history: list[str] = []
    last_sig = ""
    repeat_count = 0
    print(f"[INFO] Resolution: {width}x{height}")
    print(f"[INFO] Task: {task}")

    for step in range(1, cfg.runtime.max_steps + 1):
        screenshot_file = capture_primary_png(cfg.runtime.screenshot_path)
        screenshot_b64 = png_to_base64(screenshot_file)
        prompt = build_user_prompt(
            task=task,
            width=width,
            height=height,
            coordinate_base=cfg.display.coordinate_base,
            history=history,
        )

        decision = llm.request_decision(prompt, screenshot_b64)
        action_type = decision.action.type
        payload = decision.action.payload
        preview = f"{action_type} {payload}"
        current_sig = _action_signature(action_type, payload)

        if current_sig == last_sig:
            repeat_count += 1
        else:
            repeat_count = 1
            last_sig = current_sig

        print(f"[STEP {step}] thought={decision.thought} status={decision.status} action={preview}")
        _append_log(
            cfg.runtime.log_path,
            {
                "step": step,
                "thought": decision.thought,
                "status": decision.status,
                "confidence": decision.confidence,
                "action_type": action_type,
                "payload": payload,
            },
        )

        if decision.status == "blocked":
            print(f"[BLOCKED] {decision.reason_if_blocked}")
            return 2

        if decision.status == "completed" or action_type == "finish":
            message = payload.get("message", "Task completed.")
            print(f"[DONE] {message}")
            return 0

        if repeat_count >= 5:
            reason = (
                f"Detected repeated action {action_type} with same payload {repeat_count} times. "
                "Likely no progress (e.g. input method/focus issue)."
            )
            history.append(f"Step {step}: {reason}")
            print(f"[BLOCKED] {reason}")
            _append_log(
                cfg.runtime.log_path,
                {"step": step, "status": "blocked", "reason": reason, "action_type": action_type, "payload": payload},
            )
            return 2

        if needs_confirmation(action_type, cfg.safety.mode, cfg.safety.confirm_actions or []):
            if not confirm_action_cli(preview):
                history.append(f"Step {step}: skipped by user: {preview}")
                print(f"[STEP {step}] skipped by user.")
                continue

        try:
            result = perform_action(
                action_type=action_type,
                payload=payload,
                width=width,
                height=height,
                base=cfg.display.coordinate_base,
            )
            history.append(f"Step {step}: {result}")
        except Exception as exc:
            err = f"Step {step}: action_error: {type(exc).__name__}: {exc}"
            history.append(err)
            print(f"[ERROR] {err}")

        time.sleep(cfg.runtime.step_delay_sec)

    print("[STOP] Reached max_steps without completion.")
    return 3
