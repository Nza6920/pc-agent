from __future__ import annotations

from pathlib import Path

from desktop_agent.app import AgentHooks, AgentRunner
from desktop_agent.config import AppConfig, DisplayConfig, OpenAIConfig, RuntimeConfig, SafetyConfig
from desktop_agent.llm import LLMCallResult
from desktop_agent.schemas import LLMAction, LLMDecision


def _make_config(tmp_path: Path, *, safety_mode: str = "auto") -> AppConfig:
    return AppConfig(
        openai=OpenAIConfig(
            base_url="https://example.com/v1",
            api_key="test-key",
            model="test-model",
            timeout_sec=10,
        ),
        runtime=RuntimeConfig(
            max_steps=3,
            step_delay_sec=0.0,
            screenshot_path=str(tmp_path / "latest.png"),
            screenshot_archive_dir=str(tmp_path / "shots"),
            log_path=str(tmp_path / "session.log"),
            llm_trace_enabled=False,
        ),
        safety=SafetyConfig(
            mode=safety_mode,
            confirm_actions=["click"],
        ),
        display=DisplayConfig(
            monitor="primary",
            coordinate_base=1000,
        ),
    )


def test_agent_runner_emits_events_and_uses_confirmation(tmp_path, monkeypatch):
    cfg = _make_config(tmp_path, safety_mode="mixed")
    screenshot_path = tmp_path / "latest.png"
    screenshot_path.write_bytes(b"fake-image")

    events: list[tuple[str, dict]] = []
    confirmations: list[str] = []
    llm_calls = {"count": 0}
    performed_actions: list[tuple[str, dict]] = []

    def fake_capture(*args, **kwargs):
        return str(screenshot_path)

    def fake_b64(path: str):
        assert path == str(screenshot_path)
        return "ZmFrZQ=="

    class FakeLLMClient:
        def __init__(self, *args, **kwargs):
            pass

        def request_decision(self, prompt: str, screenshot_b64: str, image_mime_type: str):
            llm_calls["count"] += 1
            assert screenshot_b64 == "ZmFrZQ=="
            assert image_mime_type == "image/jpeg"
            if llm_calls["count"] == 1:
                return LLMCallResult(
                    decision=LLMDecision(
                        thought="click input",
                        status="in_progress",
                        confidence=0.9,
                        reason_if_blocked="",
                        action=LLMAction(type="click", payload={"x": 100, "y": 200}),
                    ),
                    trace={},
                )
            return LLMCallResult(
                decision=LLMDecision(
                    thought="done",
                    status="completed",
                    confidence=1.0,
                    reason_if_blocked="",
                    action=LLMAction(type="finish", payload={"message": "ok"}),
                ),
                trace={},
            )

    def fake_perform_action(action_type: str, payload: dict, **kwargs):
        performed_actions.append((action_type, dict(payload)))
        return f"performed {action_type}"

    monkeypatch.setattr("desktop_agent.app.enable_windows_dpi_awareness", lambda: None)
    monkeypatch.setattr("desktop_agent.app.capture_primary_image", fake_capture)
    monkeypatch.setattr("desktop_agent.app.file_to_base64", fake_b64)
    monkeypatch.setattr("desktop_agent.app.get_primary_resolution", lambda: (1920, 1080))
    monkeypatch.setattr("desktop_agent.app.get_resolution_diagnostics", lambda: {})
    monkeypatch.setattr("desktop_agent.app.LLMClient", FakeLLMClient)
    monkeypatch.setattr("desktop_agent.app.perform_action", fake_perform_action)
    monkeypatch.setattr("desktop_agent.app.time.sleep", lambda _: None)

    runner = AgentRunner(
        cfg,
        AgentHooks(
            event_handler=lambda event_type, payload: events.append((event_type, payload)),
            confirm_action=lambda summary: confirmations.append(summary) or True,
        ),
    )

    result = runner.run("test task")

    assert result.exit_code == 0
    assert llm_calls["count"] == 2
    assert confirmations == ["click {'x': 100, 'y': 200}"]
    assert [action[0] for action in performed_actions] == ["hotkey", "click"]
    event_types = [event_type for event_type, _ in events]
    assert "run_started" in event_types
    assert "screenshot_captured" in event_types
    assert "step_decision" in event_types
    assert "confirmation_requested" in event_types
    assert "confirmation_resolved" in event_types
    assert "action_executed" in event_types
    assert "done" in event_types
    assert "run_completed" in event_types


def test_agent_runner_can_stop_before_first_step(tmp_path, monkeypatch):
    cfg = _make_config(tmp_path)
    events: list[tuple[str, dict]] = []
    stop_checks = {"count": 0}

    class FakeLLMClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("LLM client should not be constructed after stop")

    def fake_perform_action(action_type: str, payload: dict, **kwargs):
        return f"performed {action_type}"

    monkeypatch.setattr("desktop_agent.app.enable_windows_dpi_awareness", lambda: None)
    monkeypatch.setattr("desktop_agent.app.get_primary_resolution", lambda: (1920, 1080))
    monkeypatch.setattr("desktop_agent.app.get_resolution_diagnostics", lambda: {})
    monkeypatch.setattr("desktop_agent.app.perform_action", fake_perform_action)
    monkeypatch.setattr("desktop_agent.app.LLMClient", FakeLLMClient)

    def should_stop() -> bool:
        stop_checks["count"] += 1
        return True

    runner = AgentRunner(
        cfg,
        AgentHooks(
            event_handler=lambda event_type, payload: events.append((event_type, payload)),
            should_stop=should_stop,
        ),
    )

    result = runner.run("test task")

    assert result.exit_code == 4
    assert stop_checks["count"] >= 1
    event_types = [event_type for event_type, _ in events]
    assert "stopped" in event_types
    assert "run_completed" in event_types
