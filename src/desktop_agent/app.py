from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .actions import perform_action
from .config import AppConfig
from .llm import LLMCallResult, LLMClient, LLMResponseParseError
from .prompts import build_user_prompt
from .safety import confirm_action_cli, needs_confirmation
from .screen import (
    capture_primary_image,
    enable_windows_dpi_awareness,
    file_to_base64,
    get_primary_resolution,
    get_resolution_diagnostics,
)

AgentEventHandler = Callable[[str, dict[str, Any]], None]
ConfirmationHandler = Callable[[str], bool]
StopCheck = Callable[[], bool]


@dataclass
class AgentHooks:
    event_handler: AgentEventHandler | None = None
    confirm_action: ConfirmationHandler | None = None
    should_stop: StopCheck | None = None


@dataclass
class AgentRunResult:
    exit_code: int
    session_id: str
    total_elapsed_sec: float


class AgentRunner:
    def __init__(self, cfg: AppConfig, hooks: AgentHooks | None = None) -> None:
        self.cfg = cfg
        self.hooks = hooks or AgentHooks()

    def run(self, task: str) -> AgentRunResult:
        total_start = time.perf_counter()
        session_id = uuid4().hex
        cfg = self.cfg
        hooks = self.hooks

        enable_windows_dpi_awareness()
        self._show_desktop()

        def _append_session_log(item: dict[str, Any]) -> None:
            payload = dict(item)
            payload.setdefault("session_id", session_id)
            self._append_log(cfg.runtime.log_path, payload)

        def _finish(code: int) -> AgentRunResult:
            total_elapsed = time.perf_counter() - total_start
            self._emit(
                "run_completed",
                session_id=session_id,
                exit_code=code,
                total_elapsed_sec=round(total_elapsed, 4),
            )
            _append_session_log(
                {
                    "type": "summary",
                    "status_code": code,
                    "total_elapsed_sec": round(total_elapsed, 4),
                },
            )
            return AgentRunResult(
                exit_code=code,
                session_id=session_id,
                total_elapsed_sec=round(total_elapsed, 4),
            )

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
            timing_payload = {
                "step": step,
                "session_id": session_id,
                "elapsed_sec": round(step_elapsed, 4),
                "capture_sec": round(capture_sec, 4),
                "encode_sec": round(encode_sec, 4),
                "llm_sec": round(llm_sec, 4),
                "action_sec": round(action_sec, 4),
                "sleep_sec": round(sleep_sec, 4),
                "end_state": end_state,
            }
            self._emit("step_timing", **timing_payload)
            _append_session_log({"type": "step_timing", **timing_payload})

        width, height = get_primary_resolution()
        diag = get_resolution_diagnostics()
        history: list[str] = []
        last_sig = ""
        repeat_count = 0
        last_semantic_sig = ""
        semantic_repeat_count = 0
        phase = "observe"
        phase_stagnant_steps = 0
        last_executed_action_type = ""

        self._emit("run_started", session_id=session_id, task=task)
        self._emit("info", message=f"Resolution: {width}x{height}")
        if diag.get("pyautogui_width") and diag.get("mss_width"):
            self._emit(
                "info",
                message=(
                    "Resolution diag: "
                    f"pyautogui={diag['pyautogui_width']}x{diag['pyautogui_height']} "
                    f"mss={diag['mss_width']}x{diag['mss_height']} "
                    f"scale=({(diag['scale_x'] or 0):.3f},{(diag['scale_y'] or 0):.3f})"
                ),
            )
            if diag["pyautogui_width"] != diag["mss_width"] or diag["pyautogui_height"] != diag["mss_height"]:
                self._emit(
                    "warning",
                    message=(
                        "Detected coordinate space mismatch between screenshot(mss) and input(pyautogui). "
                        "DPI scaling may cause click offset."
                    ),
                )
        self._emit("info", message=f"Task: {task}")
        self._emit("info", message=f"Session: {session_id}")
        self._emit("info", message="Desktop normalized with Win+D before first step.")
        self._emit(
            "info",
            message=(
                "Image optimize: "
                f"format={cfg.runtime.image_format} "
                f"max_long_edge={cfg.runtime.image_max_long_edge} "
                f"jpeg_quality={cfg.runtime.image_jpeg_quality}"
            ),
        )
        self._emit(
            "info",
            message=(
                "Guards: "
                f"exact_repeat={cfg.runtime.guard_exact_repeat_threshold} "
                f"semantic_repeat={cfg.runtime.guard_semantic_repeat_threshold} "
                f"phase_stagnant={cfg.runtime.guard_phase_stagnant_threshold}"
            ),
        )
        _append_session_log(
            {
                "type": "startup",
                "resolution_width": width,
                "resolution_height": height,
                "resolution_diag": diag,
                "desktop_normalized": True,
            },
        )

        if self._should_stop():
            self._emit("stopped", step=0, session_id=session_id, reason="Stop requested")
            _append_session_log(
                {
                    "step": 0,
                    "status": "stopped",
                    "reason": "Stop requested",
                    "phase": phase,
                },
            )
            return _finish(4)

        llm = LLMClient(
            base_url=cfg.openai.base_url,
            api_key=cfg.openai.api_key,
            model=cfg.openai.model,
            timeout_sec=cfg.openai.timeout_sec,
        )

        for step in range(1, cfg.runtime.max_steps + 1):
            if self._should_stop():
                self._emit("stopped", step=step, session_id=session_id, reason="Stop requested")
                _append_session_log(
                    {
                        "step": step,
                        "status": "stopped",
                        "reason": "Stop requested",
                        "phase": phase,
                    },
                )
                return _finish(4)

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
            archived_screenshot_file = self._archive_screenshot(
                screenshot_file,
                cfg.runtime.screenshot_archive_dir,
                session_id,
                step,
            )
            capture_sec = time.perf_counter() - t0
            self._emit(
                "screenshot_captured",
                step=step,
                session_id=session_id,
                screenshot_file=screenshot_file,
                archived_screenshot_file=archived_screenshot_file,
            )

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
                allowed_actions=self._allowed_actions_for_phase(phase),
                phase_note=self._phase_note(phase),
            )

            t0 = time.perf_counter()
            try:
                llm_result: LLMCallResult = llm.request_decision(
                    prompt,
                    screenshot_b64,
                    self._image_mime_type(cfg.runtime.image_format),
                )
            except LLMResponseParseError as exc:
                llm_sec = time.perf_counter() - t0
                if cfg.runtime.llm_trace_enabled:
                    self._write_llm_trace(
                        cfg.runtime.llm_trace_dir,
                        session_id,
                        step,
                        {
                            "step": step,
                            "session_id": session_id,
                            "timestamp": datetime.now().isoformat(timespec="seconds"),
                            "phase": phase,
                            "task": task,
                            "screenshot_file": screenshot_file,
                            "archived_screenshot_file": archived_screenshot_file,
                            "model": cfg.openai.model,
                            "trace": exc.trace,
                            "fatal_error": str(exc),
                        },
                    )
                _log_step_timing(
                    step=step,
                    step_start=step_start,
                    end_state="blocked_invalid_model_json",
                    capture_sec=capture_sec,
                    encode_sec=encode_sec,
                    llm_sec=llm_sec,
                    action_sec=action_sec,
                    sleep_sec=sleep_sec,
                )
                reason = "Model output is not valid JSON after retry."
                self._emit("blocked", step=step, session_id=session_id, reason=reason)
                _append_session_log(
                    {"step": step, "status": "blocked", "reason": reason, "phase": phase},
                )
                return _finish(2)
            llm_sec = time.perf_counter() - t0
            decision = llm_result.decision
            action_type = decision.action.type
            payload = decision.action.payload
            preview = f"{action_type} {payload}"
            current_sig = self._action_signature(action_type, payload)
            semantic_sig = self._semantic_action_signature(action_type, payload, cfg.display.coordinate_base)

            if action_type == "type_text" and cfg.runtime.guard_type_text_focus:
                if not self._type_text_focus_ready(payload=payload, last_action_type=last_executed_action_type):
                    reason = (
                        "Focus guard blocked type_text: no explicit target coordinates and no prior focus action. "
                        "Choose click/press/hotkey to focus an input field first."
                    )
                    history.append(f"Step {step}: {reason}")
                    _append_session_log(
                        {
                            "step": step,
                            "type": "guard",
                            "guard": "type_text_focus",
                            "reason": reason,
                            "action_type": action_type,
                            "payload": payload,
                            "phase": phase,
                        },
                    )
                    _log_step_timing(
                        step=step,
                        step_start=step_start,
                        end_state="guard_type_text_focus",
                        capture_sec=capture_sec,
                        encode_sec=encode_sec,
                        llm_sec=llm_sec,
                        action_sec=action_sec,
                        sleep_sec=sleep_sec,
                    )
                    self._emit(
                        "guard_blocked",
                        step=step,
                        session_id=session_id,
                        guard="type_text_focus",
                        reason=reason,
                        action_type=action_type,
                        payload=payload,
                    )
                    continue

            if cfg.runtime.llm_trace_enabled:
                self._write_llm_trace(
                    cfg.runtime.llm_trace_dir,
                    session_id,
                    step,
                    {
                        "step": step,
                        "session_id": session_id,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "phase": phase,
                        "task": task,
                        "screenshot_file": screenshot_file,
                        "archived_screenshot_file": archived_screenshot_file,
                        "model": cfg.openai.model,
                        "trace": llm_result.trace,
                        "parsed_decision": {
                            "status": decision.status,
                            "action_type": action_type,
                            "confidence": decision.confidence,
                            "thought": decision.thought,
                            "payload": payload,
                        },
                    },
                )

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

            self._emit(
                "step_decision",
                step=step,
                session_id=session_id,
                phase=phase,
                thought=decision.thought,
                status=decision.status,
                confidence=decision.confidence,
                action_type=action_type,
                payload=payload,
                preview=preview,
                screenshot_file=screenshot_file,
                archived_screenshot_file=archived_screenshot_file,
            )
            _append_session_log(
                {
                    "step": step,
                    "phase": phase,
                    "thought": decision.thought,
                    "status": decision.status,
                    "confidence": decision.confidence,
                    "action_type": action_type,
                    "payload": payload,
                    "screenshot_file": screenshot_file,
                    "archived_screenshot_file": archived_screenshot_file,
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
                self._emit(
                    "blocked",
                    step=step,
                    session_id=session_id,
                    reason=decision.reason_if_blocked,
                )
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
                self._emit("done", step=step, session_id=session_id, message=message)
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
                self._emit(
                    "blocked",
                    step=step,
                    session_id=session_id,
                    reason=reason,
                    action_type=action_type,
                    payload=payload,
                )
                _append_session_log(
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
                self._emit(
                    "blocked",
                    step=step,
                    session_id=session_id,
                    reason=reason,
                    action_type=action_type,
                    payload=payload,
                    phase=phase,
                )
                _append_session_log(
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
                approved = self._confirm_action(preview)
                if not approved:
                    history.append(f"Step {step}: skipped by user: {preview}")
                    self._emit(
                        "action_skipped",
                        step=step,
                        session_id=session_id,
                        reason="Confirmation denied",
                        preview=preview,
                    )
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
                last_executed_action_type = action_type
                phase = self._advance_phase(phase, action_type, payload)
                self._emit(
                    "action_executed",
                    step=step,
                    session_id=session_id,
                    action_type=action_type,
                    payload=payload,
                    result=result,
                    phase=phase,
                )
            except Exception as exc:
                action_sec = time.perf_counter() - t0
                err = f"Step {step}: action_error: {type(exc).__name__}: {exc}"
                history.append(err)
                self._emit(
                    "action_error",
                    step=step,
                    session_id=session_id,
                    error=err,
                    action_type=action_type,
                    payload=payload,
                )

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
                self._emit("blocked", step=step, session_id=session_id, reason=reason, phase=phase)
                _append_session_log(
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

        self._emit("stopped", session_id=session_id, reason="Reached max_steps without completion")
        return _finish(3)

    def _emit(self, event_type: str, **payload: Any) -> None:
        if self.hooks.event_handler is None:
            return
        self.hooks.event_handler(event_type, payload)

    def _confirm_action(self, action_summary: str) -> bool:
        self._emit("confirmation_requested", preview=action_summary)
        confirm_action = self.hooks.confirm_action or confirm_action_cli
        approved = confirm_action(action_summary)
        self._emit("confirmation_resolved", preview=action_summary, approved=approved)
        return approved

    def _should_stop(self) -> bool:
        if self.hooks.should_stop is None:
            return False
        try:
            return bool(self.hooks.should_stop())
        except Exception:
            return False

    @staticmethod
    def _show_desktop() -> None:
        # Normalize the UI before the first screenshot so the agent starts from a stable state.
        perform_action(
            action_type="hotkey",
            payload={"keys": ["win", "d"]},
            width=1,
            height=1,
            base=1,
        )

    @staticmethod
    def _archive_screenshot(path: str, archive_dir: str, session_id: str, step: int) -> str:
        source = Path(path)
        target_dir = Path(archive_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        ext = source.suffix or ".png"
        target = target_dir / f"{session_id}_step_{step:04d}{ext}"
        shutil.copy2(source, target)
        return str(target)

    @staticmethod
    def _append_log(path: str, item: dict[str, Any]) -> None:
        log_file = Path(path)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    @staticmethod
    def _write_llm_trace(trace_dir: str, session_id: str, step: int, trace_payload: dict[str, Any]) -> None:
        out_dir = Path(trace_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = out_dir / f"{session_id}_step_{step:04d}_{ts}.json"
        out_file.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _action_signature(action_type: str, payload: dict[str, Any]) -> str:
        return f"{action_type}:{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"

    @staticmethod
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

    @staticmethod
    def _allowed_actions_for_phase(phase: str) -> list[str]:
        mapping = {
            "observe": [
                "move",
                "wait",
                "click",
                "double_click",
                "right_click",
                "scroll",
                "press",
                "hotkey",
                "type_text",
                "finish",
            ],
            "execute": [
                "move",
                "wait",
                "click",
                "double_click",
                "right_click",
                "scroll",
                "press",
                "hotkey",
                "type_text",
                "finish",
            ],
            "finalize": ["click", "press", "hotkey", "type_text", "wait", "finish"],
        }
        return mapping.get(phase, mapping["execute"])

    @staticmethod
    def _phase_note(phase: str) -> str:
        notes = {
            "observe": "Understand current UI state with one low-risk action.",
            "execute": "Progress the task with minimal reversible actions.",
            "finalize": "Task appears close to completion; verify and finish when satisfied.",
        }
        return notes.get(phase, "Proceed safely with one minimal action.")

    @staticmethod
    def _advance_phase(current_phase: str, action_type: str, payload: dict[str, Any]) -> str:
        _ = payload
        if action_type == "finish":
            return "finalize"
        if current_phase == "observe":
            return "execute"
        return current_phase

    @staticmethod
    def _image_mime_type(image_format: str) -> str:
        fmt = image_format.lower()
        if fmt == "jpeg":
            return "image/jpeg"
        if fmt == "png":
            return "image/png"
        return "application/octet-stream"

    @staticmethod
    def _type_text_focus_ready(*, payload: dict[str, Any], last_action_type: str) -> bool:
        if "x" in payload and "y" in payload:
            return True
        return last_action_type in {"click", "double_click", "right_click", "press", "hotkey"}


def _build_cli_event_handler() -> AgentEventHandler:
    def _handle(event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "info":
            print(f"[INFO] {payload['message']}")
        elif event_type == "warning":
            print(f"[WARN] {payload['message']}")
        elif event_type == "step_decision":
            print(
                f"[STEP {payload['step']}] phase={payload['phase']} thought={payload['thought']} "
                f"status={payload['status']} action={payload['preview']}"
            )
        elif event_type == "step_timing":
            print(
                f"[STEP {payload['step']}] elapsed={payload['elapsed_sec']:.2f}s "
                f"(capture={payload['capture_sec']:.2f}s encode={payload['encode_sec']:.2f}s "
                f"llm={payload['llm_sec']:.2f}s action={payload['action_sec']:.2f}s "
                f"sleep={payload['sleep_sec']:.2f}s)"
            )
        elif event_type == "guard_blocked":
            print(f"[GUARD] {payload['reason']}")
        elif event_type == "blocked":
            print(f"[BLOCKED] {payload['reason']}")
        elif event_type == "done":
            print(f"[DONE] {payload['message']}")
        elif event_type == "action_skipped":
            print(f"[STEP {payload['step']}] skipped by user.")
        elif event_type == "action_error":
            print(f"[ERROR] {payload['error']}")
        elif event_type == "stopped":
            print(f"[STOP] {payload['reason']}")
        elif event_type == "run_completed":
            print(f"[TOTAL] elapsed={payload['total_elapsed_sec']:.2f}s")

    return _handle


def run_agent(task: str, cfg: AppConfig) -> int:
    runner = AgentRunner(
        cfg,
        AgentHooks(
            event_handler=_build_cli_event_handler(),
            confirm_action=confirm_action_cli,
        ),
    )
    return runner.run(task).exit_code
