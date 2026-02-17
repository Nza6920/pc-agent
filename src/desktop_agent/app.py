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
from .screen import capture_primary_image, file_to_base64, get_primary_resolution


def _append_log(path: str, item: dict) -> None:
    log_file = Path(path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _action_signature(action_type: str, payload: dict[str, Any]) -> str:
    return f"{action_type}:{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"


def _semantic_action_signature(action_type: str, payload: dict[str, Any], coordinate_base: int) -> str:
    def _bucket(v: Any, bucket_size: int = 80) -> int:
        try:
            iv = int(float(v))
        except Exception:
            return -1
        iv = max(0, min(coordinate_base, iv))
        return iv // bucket_size

    if action_type in {"click", "double_click", "right_click", "move"}:
        xb = _bucket(payload.get("x"))
        yb = _bucket(payload.get("y"))
        button = str(payload.get("button", "left"))
        return f"{action_type}:b{button}:x{xb}:y{yb}"
    if action_type == "type_text":
        text = str(payload.get("text", "")).strip().lower()
        text_norm = text[:12]
        return f"type_text:len{len(text)}:{text_norm}"
    if action_type == "hotkey":
        keys = payload.get("keys")
        if isinstance(keys, list):
            return f"hotkey:{'+'.join(str(k).lower() for k in keys)}"
    if action_type == "press":
        key = str(payload.get("key", "")).lower()
        return f"press:{key}"
    if action_type == "wait":
        sec = payload.get("seconds", 1.0)
        try:
            return f"wait:{round(float(sec), 1)}"
        except Exception:
            return "wait:unknown"
    return f"{action_type}:generic"


def _allowed_actions_for_phase(phase: str) -> list[str]:
    mapping = {
        "observe": ["move", "wait", "click", "double_click", "right_click", "scroll", "press", "hotkey", "type_text", "finish"],
        "execute": ["move", "wait", "click", "double_click", "right_click", "scroll", "press", "hotkey", "type_text", "finish"],
        "finalize": ["click", "press", "hotkey", "type_text", "wait", "finish"],
    }
    return mapping.get(phase, mapping["execute"])


def _phase_note(phase: str) -> str:
    notes = {
        "observe": "Understand current UI state with one low-risk action.",
        "execute": "Progress the task with minimal reversible actions.",
        "finalize": "Task appears close to completion; verify and finish when satisfied.",
    }
    return notes.get(phase, "Proceed safely with one minimal action.")


def _advance_phase(
    current_phase: str,
    action_type: str,
    payload: dict[str, Any],
) -> str:
    _ = payload
    if action_type == "finish":
        return "finalize"
    if current_phase == "observe":
        return "execute"
    return current_phase


def _image_mime_type(image_format: str) -> str:
    fmt = image_format.lower()
    if fmt == "jpeg":
        return "image/jpeg"
    if fmt == "png":
        return "image/png"
    return "application/octet-stream"


def run_agent(task: str, cfg: AppConfig) -> int:
    total_start = time.perf_counter()

    def _finish(code: int) -> int:
        total_elapsed = time.perf_counter() - total_start
        print(f"[TOTAL] elapsed={total_elapsed:.2f}s")
        _append_log(
            cfg.runtime.log_path,
            {
                "type": "summary",
                "status_code": code,
                "total_elapsed_sec": round(total_elapsed, 4),
            },
        )
        return code

    def _log_step_timing(
        *,
        step: int,
        step_start: float,
        end_state: str,
        capture_sec: float,
        encode_sec: float,
        llm_sec: float,
        action_sec: float,
        sleep_sec: float,
    ) -> None:
        step_elapsed = time.perf_counter() - step_start
        print(
            f"[STEP {step}] elapsed={step_elapsed:.2f}s "
            f"(capture={capture_sec:.2f}s encode={encode_sec:.2f}s llm={llm_sec:.2f}s "
            f"action={action_sec:.2f}s sleep={sleep_sec:.2f}s)"
        )
        _append_log(
            cfg.runtime.log_path,
            {
                "step": step,
                "type": "step_timing",
                "elapsed_sec": round(step_elapsed, 4),
                "capture_sec": round(capture_sec, 4),
                "encode_sec": round(encode_sec, 4),
                "llm_sec": round(llm_sec, 4),
                "action_sec": round(action_sec, 4),
                "sleep_sec": round(sleep_sec, 4),
                "end_state": end_state,
            },
        )

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
    last_semantic_sig = ""
    semantic_repeat_count = 0
    phase = "observe"
    phase_stagnant_steps = 0
    print(f"[INFO] Resolution: {width}x{height}")
    print(f"[INFO] Task: {task}")
    print(
        "[INFO] Image optimize: "
        f"format={cfg.runtime.image_format} "
        f"max_long_edge={cfg.runtime.image_max_long_edge} "
        f"jpeg_quality={cfg.runtime.image_jpeg_quality}"
    )
    print(
        "[INFO] Guards: "
        f"exact_repeat={cfg.runtime.guard_exact_repeat_threshold} "
        f"semantic_repeat={cfg.runtime.guard_semantic_repeat_threshold} "
        f"phase_stagnant={cfg.runtime.guard_phase_stagnant_threshold}"
    )

    for step in range(1, cfg.runtime.max_steps + 1):
        step_start = time.perf_counter()
        capture_sec = 0.0
        encode_sec = 0.0
        llm_sec = 0.0
        action_sec = 0.0
        sleep_sec = 0.0

        t0 = time.perf_counter()
        screenshot_file = capture_primary_image(
            cfg.runtime.screenshot_path,
            image_format=cfg.runtime.image_format,
            max_long_edge=cfg.runtime.image_max_long_edge,
            jpeg_quality=cfg.runtime.image_jpeg_quality,
        )
        capture_sec = time.perf_counter() - t0

        t0 = time.perf_counter()
        screenshot_b64 = file_to_base64(screenshot_file)
        encode_sec = time.perf_counter() - t0

        prompt = build_user_prompt(
            task=task,
            width=width,
            height=height,
            coordinate_base=cfg.display.coordinate_base,
            history=history,
            phase=phase,
            allowed_actions=_allowed_actions_for_phase(phase),
            phase_note=_phase_note(phase),
        )

        t0 = time.perf_counter()
        decision = llm.request_decision(prompt, screenshot_b64, _image_mime_type(cfg.runtime.image_format))
        llm_sec = time.perf_counter() - t0
        action_type = decision.action.type
        payload = decision.action.payload
        preview = f"{action_type} {payload}"
        current_sig = _action_signature(action_type, payload)
        semantic_sig = _semantic_action_signature(action_type, payload, cfg.display.coordinate_base)

        if current_sig == last_sig:
            repeat_count += 1
        else:
            repeat_count = 1
            last_sig = current_sig

        if semantic_sig == last_semantic_sig:
            semantic_repeat_count += 1
            phase_stagnant_steps += 1
        else:
            semantic_repeat_count = 1
            last_semantic_sig = semantic_sig
            phase_stagnant_steps = 0

        print(
            f"[STEP {step}] phase={phase} thought={decision.thought} "
            f"status={decision.status} action={preview}"
        )
        _append_log(
            cfg.runtime.log_path,
            {
                "step": step,
                "phase": phase,
                "thought": decision.thought,
                "status": decision.status,
                "confidence": decision.confidence,
                "action_type": action_type,
                "payload": payload,
            },
        )

        if decision.status == "blocked":
            _log_step_timing(
                step=step,
                step_start=step_start,
                end_state="blocked",
                capture_sec=capture_sec,
                encode_sec=encode_sec,
                llm_sec=llm_sec,
                action_sec=action_sec,
                sleep_sec=sleep_sec,
            )
            print(f"[BLOCKED] {decision.reason_if_blocked}")
            return _finish(2)

        if decision.status == "completed" or action_type == "finish":
            _log_step_timing(
                step=step,
                step_start=step_start,
                end_state="completed",
                capture_sec=capture_sec,
                encode_sec=encode_sec,
                llm_sec=llm_sec,
                action_sec=action_sec,
                sleep_sec=sleep_sec,
            )
            message = payload.get("message", "Task completed.")
            print(f"[DONE] {message}")
            return _finish(0)

        if repeat_count >= cfg.runtime.guard_exact_repeat_threshold:
            reason = (
                f"Detected repeated action {action_type} with same payload {repeat_count} times. "
                "Likely no progress (e.g. input method/focus issue)."
            )
            history.append(f"Step {step}: {reason}")
            _log_step_timing(
                step=step,
                step_start=step_start,
                end_state="blocked_repeat",
                capture_sec=capture_sec,
                encode_sec=encode_sec,
                llm_sec=llm_sec,
                action_sec=action_sec,
                sleep_sec=sleep_sec,
            )
            print(f"[BLOCKED] {reason}")
            _append_log(
                cfg.runtime.log_path,
                {"step": step, "status": "blocked", "reason": reason, "action_type": action_type, "payload": payload},
            )
            return _finish(2)

        if semantic_repeat_count >= cfg.runtime.guard_semantic_repeat_threshold:
            reason = (
                f"Detected semantic repeated action pattern {semantic_sig} for {semantic_repeat_count} steps. "
                "No progress likely; forcing strategy change by blocking."
            )
            history.append(f"Step {step}: {reason}")
            _log_step_timing(
                step=step,
                step_start=step_start,
                end_state="blocked_semantic_repeat",
                capture_sec=capture_sec,
                encode_sec=encode_sec,
                llm_sec=llm_sec,
                action_sec=action_sec,
                sleep_sec=sleep_sec,
            )
            print(f"[BLOCKED] {reason}")
            _append_log(
                cfg.runtime.log_path,
                {
                    "step": step,
                    "status": "blocked",
                    "reason": reason,
                    "action_type": action_type,
                    "payload": payload,
                    "phase": phase,
                },
            )
            return _finish(2)

        if needs_confirmation(action_type, cfg.safety.mode, cfg.safety.confirm_actions or []):
            if not confirm_action_cli(preview):
                history.append(f"Step {step}: skipped by user: {preview}")
                print(f"[STEP {step}] skipped by user.")
                _log_step_timing(
                    step=step,
                    step_start=step_start,
                    end_state="skipped_by_user",
                    capture_sec=capture_sec,
                    encode_sec=encode_sec,
                    llm_sec=llm_sec,
                    action_sec=action_sec,
                    sleep_sec=sleep_sec,
                )
                continue

        try:
            t0 = time.perf_counter()
            result = perform_action(
                action_type=action_type,
                payload=payload,
                width=width,
                height=height,
                base=cfg.display.coordinate_base,
            )
            action_sec = time.perf_counter() - t0
            history.append(f"Step {step}: {result}")

            phase = _advance_phase(
                phase,
                action_type,
                payload,
            )
        except Exception as exc:
            action_sec = time.perf_counter() - t0
            err = f"Step {step}: action_error: {type(exc).__name__}: {exc}"
            history.append(err)
            print(f"[ERROR] {err}")

        if cfg.runtime.guard_phase_stagnant_threshold > 0 and phase_stagnant_steps >= cfg.runtime.guard_phase_stagnant_threshold:
            reason = f"Execution phase '{phase}' stagnated for {phase_stagnant_steps} steps."
            _log_step_timing(
                step=step,
                step_start=step_start,
                end_state="blocked_phase_stagnant",
                capture_sec=capture_sec,
                encode_sec=encode_sec,
                llm_sec=llm_sec,
                action_sec=action_sec,
                sleep_sec=sleep_sec,
            )
            print(f"[BLOCKED] {reason}")
            _append_log(
                cfg.runtime.log_path,
                {"step": step, "status": "blocked", "reason": reason, "phase": phase},
            )
            return _finish(2)

        t0 = time.perf_counter()
        time.sleep(cfg.runtime.step_delay_sec)
        sleep_sec = time.perf_counter() - t0
        _log_step_timing(
            step=step,
            step_start=step_start,
            end_state="continue",
            capture_sec=capture_sec,
            encode_sec=encode_sec,
            llm_sec=llm_sec,
            action_sec=action_sec,
            sleep_sec=sleep_sec,
        )

    print("[STOP] Reached max_steps without completion.")
    return _finish(3)
