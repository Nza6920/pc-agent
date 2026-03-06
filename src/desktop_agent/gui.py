from __future__ import annotations

import queue
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from .config import load_config

if TYPE_CHECKING:
    from .config import AppConfig

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError as exc:  # pragma: no cover - depends on optional extra
    QtCore = QtGui = QtWidgets = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


@dataclass
class GuiEvent:
    type: str
    payload: dict[str, Any]


@dataclass
class ConfirmationRequest:
    preview: str
    response_ready: threading.Event
    approved: bool | None = None


class RunnerSession:
    def __init__(self, cfg: "AppConfig", task: str) -> None:
        self.cfg = cfg
        self.task = task
        self.events: queue.Queue[GuiEvent] = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="desktop-agent-gui-runner", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def request_stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        try:
            from .app import AgentHooks, AgentRunner

            runner = AgentRunner(
                self.cfg,
                AgentHooks(
                    event_handler=self._push_event,
                    confirm_action=self._confirm_action,
                    should_stop=self.stop_event.is_set,
                ),
            )
            result = runner.run(self.task)
            self._emit_event(
                "session_finished",
                exit_code=result.exit_code,
                session_id=result.session_id,
                total_elapsed_sec=result.total_elapsed_sec,
            )
        except Exception as exc:
            self._emit_event(
                "session_error",
                error=str(exc),
                traceback=traceback.format_exc(),
            )

    def _confirm_action(self, action_summary: str) -> bool:
        request = ConfirmationRequest(
            preview=action_summary,
            response_ready=threading.Event(),
        )
        self._emit_event("confirmation_needed", request=request)
        request.response_ready.wait()
        return bool(request.approved)

    def _push_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.put(GuiEvent(type=event_type, payload=payload))

    def _emit_event(self, event_type: str, **payload: Any) -> None:
        self.events.put(GuiEvent(type=event_type, payload=payload))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_config_path() -> Path:
    cwd_candidate = Path.cwd() / "config.yaml"
    if cwd_candidate.exists():
        return cwd_candidate.resolve()
    project_candidate = _project_root() / "config.yaml"
    if project_candidate.exists():
        return project_candidate.resolve()
    return project_candidate


def _resolve_config_path(path_text: str) -> Path:
    raw = Path(path_text).expanduser()
    if raw.is_absolute():
        return raw

    cwd_candidate = (Path.cwd() / raw).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    project_candidate = (_project_root() / raw).resolve()
    if project_candidate.exists():
        return project_candidate

    return cwd_candidate


def _format_phase(phase: str) -> str:
    mapping = {
        "observe": "Observe",
        "execute": "Execute",
        "finalize": "Finalize",
    }
    return mapping.get(phase, phase or "-")


def _format_run_status(status: str) -> str:
    mapping = {
        "idle": "Idle",
        "running": "Running",
        "in_progress": "Running",
        "completed": "Completed",
        "blocked": "Blocked",
        "stopped": "Stopped",
        "stopping": "Stopping",
        "error": "Error",
    }
    return mapping.get(status.lower(), status)


def _status_from_exit_code(exit_code: int) -> str:
    mapping = {
        0: "Completed",
        2: "Blocked",
        3: "Stopped",
        4: "Stopped",
    }
    return mapping.get(exit_code, f"Exit {exit_code}")


if QtWidgets is not None:
    class MainWindow(QtWidgets.QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Desktop Agent GUI")
            self.resize(1360, 860)

            self._session: RunnerSession | None = None
            self._latest_screenshot_path: str = ""
            self._last_status: str = "Idle"
            self._build_ui()

            self._poll_timer = QtCore.QTimer(self)
            self._poll_timer.setInterval(100)
            self._poll_timer.timeout.connect(self._drain_events)

        def _build_ui(self) -> None:
            central = QtWidgets.QWidget(self)
            self.setCentralWidget(central)

            root = QtWidgets.QHBoxLayout(central)
            root.setContentsMargins(16, 16, 16, 16)
            root.setSpacing(16)

            left = QtWidgets.QFrame()
            left.setMinimumWidth(380)
            left.setMaximumWidth(460)
            left_layout = QtWidgets.QVBoxLayout(left)
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.setSpacing(12)

            title = QtWidgets.QLabel("Desktop Agent")
            title_font = QtGui.QFont("Microsoft YaHei UI", 18, QtGui.QFont.Weight.Bold)
            title.setFont(title_font)
            left_layout.addWidget(title)

            subtitle = QtWidgets.QLabel("Task runner, screenshot preview, and action approvals")
            subtitle.setWordWrap(True)
            subtitle.setStyleSheet("color: #52606d;")
            left_layout.addWidget(subtitle)

            config_group = QtWidgets.QGroupBox("Config")
            config_layout = QtWidgets.QGridLayout(config_group)
            config_layout.setHorizontalSpacing(8)
            config_layout.setVerticalSpacing(8)

            self.config_path_edit = QtWidgets.QLineEdit(str(_default_config_path()))
            browse_button = QtWidgets.QPushButton("Browse")
            browse_button.clicked.connect(self._browse_config)
            reload_button = QtWidgets.QPushButton("Load")
            reload_button.clicked.connect(self._load_config_preview)
            self.save_config_button = QtWidgets.QPushButton("Save")
            self.save_config_button.clicked.connect(self._save_config_form)

            config_layout.addWidget(QtWidgets.QLabel("Path"), 0, 0)
            config_layout.addWidget(self.config_path_edit, 0, 1)
            config_layout.addWidget(browse_button, 0, 2)
            config_layout.addWidget(reload_button, 0, 3)
            config_layout.addWidget(self.save_config_button, 0, 4)

            form_widget = QtWidgets.QWidget()
            form_layout = QtWidgets.QFormLayout(form_widget)
            form_layout.setContentsMargins(0, 0, 0, 0)
            form_layout.setSpacing(8)

            self.model_edit = QtWidgets.QLineEdit()
            self.base_url_edit = QtWidgets.QLineEdit()
            self.base_url_edit.setPlaceholderText("https://api.example.com/v1")
            self.api_key_edit = QtWidgets.QLineEdit()
            self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
            self.api_key_edit.setPlaceholderText("OpenAI-compatible API key")
            self.api_key_toggle_button = QtWidgets.QToolButton()
            self.api_key_toggle_button.setText("Show")
            self.api_key_toggle_button.clicked.connect(self._toggle_api_key_visibility)
            api_key_widget = QtWidgets.QWidget()
            api_key_layout = QtWidgets.QHBoxLayout(api_key_widget)
            api_key_layout.setContentsMargins(0, 0, 0, 0)
            api_key_layout.setSpacing(6)
            api_key_layout.addWidget(self.api_key_edit, 1)
            api_key_layout.addWidget(self.api_key_toggle_button)
            self.safety_mode_combo = QtWidgets.QComboBox()
            self.safety_mode_combo.addItems(["mixed", "manual", "auto"])
            self.max_steps_spin = QtWidgets.QSpinBox()
            self.max_steps_spin.setRange(1, 10000)
            self.max_steps_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
            self.max_steps_spin.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            self.step_delay_spin = QtWidgets.QDoubleSpinBox()
            self.step_delay_spin.setRange(0.0, 60.0)
            self.step_delay_spin.setDecimals(2)
            self.step_delay_spin.setSingleStep(0.1)
            self.step_delay_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
            self.step_delay_spin.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

            form_layout.addRow("Model", self.model_edit)
            form_layout.addRow("Base URL", self.base_url_edit)
            form_layout.addRow("API Key", api_key_widget)
            form_layout.addRow("Safety", self.safety_mode_combo)
            form_layout.addRow("Max Steps", self.max_steps_spin)
            form_layout.addRow("Step Delay (s)", self.step_delay_spin)

            config_layout.addWidget(form_widget, 1, 0, 1, 5)

            self.config_summary = QtWidgets.QPlainTextEdit()
            self.config_summary.setReadOnly(True)
            self.config_summary.setMaximumBlockCount(100)
            self.config_summary.setPlaceholderText("Load a config file to preview runtime settings.")
            config_layout.addWidget(self.config_summary, 2, 0, 1, 5)
            left_layout.addWidget(config_group)

            task_group = QtWidgets.QGroupBox("Task")
            task_layout = QtWidgets.QVBoxLayout(task_group)
            task_layout.setContentsMargins(12, 12, 12, 12)

            self.task_edit = QtWidgets.QPlainTextEdit()
            self.task_edit.setPlaceholderText("Describe the desktop task to execute...")
            self.task_edit.setMinimumHeight(170)
            task_layout.addWidget(self.task_edit)
            left_layout.addWidget(task_group)

            controls_group = QtWidgets.QGroupBox("Controls")
            controls_layout = QtWidgets.QHBoxLayout(controls_group)
            controls_layout.setContentsMargins(12, 12, 12, 12)

            self.start_button = QtWidgets.QPushButton("Start")
            self.start_button.clicked.connect(self._start_run)
            self.stop_button = QtWidgets.QPushButton("Stop")
            self.stop_button.clicked.connect(self._stop_run)
            self.stop_button.setEnabled(False)
            controls_layout.addWidget(self.start_button)
            controls_layout.addWidget(self.stop_button)
            left_layout.addWidget(controls_group)

            self.status_card = QtWidgets.QFrame()
            self.status_card.setObjectName("statusCard")
            status_layout = QtWidgets.QVBoxLayout(self.status_card)
            status_layout.setContentsMargins(12, 12, 12, 12)
            status_layout.setSpacing(6)

            self.status_label = QtWidgets.QLabel("Idle")
            status_font = QtGui.QFont("Microsoft YaHei UI", 12, QtGui.QFont.Weight.DemiBold)
            self.status_label.setFont(status_font)
            self.status_title_label = QtWidgets.QLabel("Run Status")
            self.session_label = QtWidgets.QLabel("Session: -")
            self.step_label = QtWidgets.QLabel("Step: -")
            self.phase_label = QtWidgets.QLabel("Phase: -")
            status_layout.addWidget(self.status_title_label)
            status_layout.addWidget(self.status_label)
            status_layout.addWidget(self.session_label)
            status_layout.addWidget(self.step_label)
            status_layout.addWidget(self.phase_label)
            left_layout.addWidget(self.status_card)
            left_layout.addStretch(1)

            right = QtWidgets.QWidget()
            right_layout = QtWidgets.QVBoxLayout(right)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(12)

            preview_group = QtWidgets.QGroupBox("Latest Screenshot")
            preview_layout = QtWidgets.QVBoxLayout(preview_group)
            preview_layout.setContentsMargins(12, 12, 12, 12)

            self.screenshot_label = QtWidgets.QLabel("No screenshot yet")
            self.screenshot_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.screenshot_label.setMinimumHeight(420)
            self.screenshot_label.setStyleSheet(
                "background: #0f172a; color: #e2e8f0; border: 1px solid #cbd5e1; border-radius: 8px;"
            )
            preview_layout.addWidget(self.screenshot_label)
            self.screenshot_meta_label = QtWidgets.QLabel("Path: -")
            self.screenshot_meta_label.setWordWrap(True)
            preview_layout.addWidget(self.screenshot_meta_label)
            right_layout.addWidget(preview_group, 3)

            log_group = QtWidgets.QGroupBox("Event Log")
            log_layout = QtWidgets.QVBoxLayout(log_group)
            log_layout.setContentsMargins(12, 12, 12, 12)

            self.log_view = QtWidgets.QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.setMaximumBlockCount(1500)
            log_layout.addWidget(self.log_view)
            right_layout.addWidget(log_group, 2)

            root.addWidget(left)
            root.addWidget(right, 1)

            self.setStyleSheet(
                """
                QMainWindow { background: #f4f7fb; }
                QWidget { color: #102a43; }
                QLabel { color: #243b53; }
                QGroupBox {
                    background: white;
                    border: 1px solid #d9e2ec;
                    border-radius: 10px;
                    margin-top: 12px;
                    font-weight: 600;
                    color: #486581;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 4px 0 4px;
                }
                QPushButton {
                    background: #0f62fe;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    min-height: 36px;
                    padding: 0 16px;
                }
                QPushButton:disabled {
                    background: #9fb3c8;
                }
                QLineEdit, QPlainTextEdit {
                    border: 1px solid #bcccdc;
                    border-radius: 8px;
                    background: white;
                    color: #102a43;
                    selection-background-color: #0f62fe;
                    selection-color: white;
                    padding: 8px;
                }
                QLineEdit[readOnly="false"] {
                    color: #102a43;
                }
                QComboBox, QSpinBox, QDoubleSpinBox {
                    border: 1px solid #bcccdc;
                    border-radius: 8px;
                    background: white;
                    color: #102a43;
                    min-height: 32px;
                    padding: 2px 8px;
                }
                QSpinBox::up-button, QSpinBox::down-button,
                QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                    width: 0px;
                    border: none;
                    padding: 0px;
                    margin: 0px;
                }
                QComboBox QAbstractItemView {
                    background: white;
                    color: #102a43;
                    border: 1px solid #bcccdc;
                    selection-background-color: #d9e8ff;
                    selection-color: #102a43;
                    outline: none;
                }
                #statusCard {
                    background: #102a43;
                    color: #f0f4f8;
                    border-radius: 12px;
                }
                #statusCard QLabel {
                    color: #f0f4f8;
                }
                """
            )

        def _browse_config(self) -> None:
            current_path = _resolve_config_path(self.config_path_edit.text() or "config.yaml")
            file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select config file",
                str(current_path),
                "YAML Files (*.yaml *.yml);;All Files (*)",
            )
            if file_path:
                self.config_path_edit.setText(file_path)
                self._load_config_preview()

        def _load_config_preview(self) -> None:
            path_text = self.config_path_edit.text().strip()
            if not path_text:
                self._show_error("Config path is empty.")
                return
            path = _resolve_config_path(path_text)
            try:
                cfg = load_config(str(path))
            except Exception as exc:
                self.config_summary.setPlainText(f"Failed to load config:\n{exc}")
                self._append_log(f"[ERROR] failed to load config: {exc}")
                return

            self.config_path_edit.setText(str(path))
            summary = [
                f"model={cfg.openai.model}",
                f"base_url={cfg.openai.base_url}",
                f"safety_mode={cfg.safety.mode}",
                f"max_steps={cfg.runtime.max_steps}",
                f"step_delay_sec={cfg.runtime.step_delay_sec}",
                f"image_format={cfg.runtime.image_format}",
                f"log_path={cfg.runtime.log_path}",
                f"screenshot_path={cfg.runtime.screenshot_path}",
            ]
            self.model_edit.setText(cfg.openai.model)
            self.base_url_edit.setText(cfg.openai.base_url)
            self.api_key_edit.setText(cfg.openai.api_key)
            self.safety_mode_combo.setCurrentText(cfg.safety.mode)
            self.max_steps_spin.setValue(cfg.runtime.max_steps)
            self.step_delay_spin.setValue(cfg.runtime.step_delay_sec)
            self.config_summary.setPlainText("\n".join(summary))
            self._append_log(f"[INFO] config loaded: {path}")

        def _save_config_form(self) -> None:
            path_text = self.config_path_edit.text().strip()
            if not path_text:
                self._show_error("Config path is empty.")
                return

            path = _resolve_config_path(path_text)
            try:
                raw_text = path.read_text(encoding="utf-8")
                data = yaml.safe_load(raw_text) or {}
            except Exception as exc:
                self._show_error(f"Failed to read config for saving:\n{exc}")
                return

            openai_data = data.setdefault("openai", {})
            runtime_data = data.setdefault("runtime", {})
            safety_data = data.setdefault("safety", {})

            openai_data["model"] = self.model_edit.text().strip()
            openai_data["base_url"] = self.base_url_edit.text().strip()
            openai_data["api_key"] = self.api_key_edit.text().strip()
            runtime_data["max_steps"] = int(self.max_steps_spin.value())
            runtime_data["step_delay_sec"] = float(self.step_delay_spin.value())
            safety_data["mode"] = self.safety_mode_combo.currentText()

            try:
                path.write_text(
                    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception as exc:
                self._show_error(f"Failed to save config:\n{exc}")
                return

            self.config_path_edit.setText(str(path))
            self._append_log(f"[INFO] config saved: {path}")
            self._load_config_preview()

        def _start_run(self) -> None:
            if self._session is not None:
                self._show_error("A session is already running.")
                return

            task = self.task_edit.toPlainText().strip()
            if not task:
                self._show_error("Task cannot be empty.")
                return

            config_path_text = self.config_path_edit.text().strip()
            if not config_path_text:
                self._show_error("Config path cannot be empty.")
                return

            config_path = _resolve_config_path(config_path_text)
            try:
                cfg = load_config(str(config_path))
            except Exception as exc:
                self._show_error(f"Failed to load config:\n{exc}")
                return

            self.config_path_edit.setText(str(config_path))
            self.log_view.clear()
            self._session = RunnerSession(cfg, task)
            self._set_running(True)
            self._set_status("Running")
            self.step_label.setText("Step: -")
            self.phase_label.setText(f"Phase: {_format_phase('observe')}")
            self.session_label.setText("Session: pending")
            self.screenshot_meta_label.setText("Path: waiting for first capture")
            self._append_log(f"[INFO] starting task: {task}")
            self._poll_timer.start()
            self._session.start()

        def _stop_run(self) -> None:
            if self._session is None:
                return
            self._session.request_stop()
            self._set_status("Stopping")
            self._append_log("[INFO] stop requested")

        def _drain_events(self) -> None:
            if self._session is None:
                self._poll_timer.stop()
                return

            while True:
                try:
                    event = self._session.events.get_nowait()
                except queue.Empty:
                    break
                self._handle_event(event)

            if not self._session.thread.is_alive() and self._session.events.empty():
                self._poll_timer.stop()
                self._session = None
                self._set_running(False)

        def _handle_event(self, event: GuiEvent) -> None:
            event_type = event.type
            payload = event.payload

            if event_type == "run_started":
                self.session_label.setText(f"Session: {payload['session_id']}")
                self._append_log(f"[INFO] session started: {payload['session_id']}")
                return

            if event_type == "info":
                self._append_log(f"[INFO] {payload['message']}")
                return

            if event_type == "warning":
                self._append_log(f"[WARN] {payload['message']}")
                return

            if event_type == "screenshot_captured":
                self._update_screenshot(payload["screenshot_file"])
                archived = payload.get("archived_screenshot_file", "")
                self.screenshot_meta_label.setText(
                    f"Path: {payload['screenshot_file']}\nArchive: {archived}"
                )
                return

            if event_type == "step_decision":
                self.step_label.setText(f"Step: {payload['step']}")
                self.phase_label.setText(f"Phase: {_format_phase(payload['phase'])}")
                self._set_status(payload["status"])
                self._append_log(
                    f"[STEP {payload['step']}] {payload['status']} {payload['action_type']} "
                    f"{payload['payload']} thought={payload['thought']}"
                )
                return

            if event_type == "step_timing":
                self._append_log(
                    f"[TIMING {payload['step']}] total={payload['elapsed_sec']:.2f}s "
                    f"llm={payload['llm_sec']:.2f}s action={payload['action_sec']:.2f}s "
                    f"end={payload['end_state']}"
                )
                return

            if event_type == "confirmation_needed":
                request: ConfirmationRequest = payload["request"]
                approved = self._ask_confirmation(request.preview)
                request.approved = approved
                request.response_ready.set()
                return

            if event_type == "confirmation_requested":
                self._append_log(f"[CONFIRM] waiting for approval: {payload['preview']}")
                return

            if event_type == "confirmation_resolved":
                state = "approved" if payload["approved"] else "rejected"
                self._append_log(f"[CONFIRM] {state}: {payload['preview']}")
                return

            if event_type == "action_executed":
                self._append_log(
                    f"[ACTION {payload['step']}] {payload['action_type']} -> {payload['result']}"
                )
                return

            if event_type == "action_skipped":
                self._append_log(f"[SKIP {payload['step']}] {payload['preview']}")
                return

            if event_type == "guard_blocked":
                self._append_log(f"[GUARD] {payload['reason']}")
                return

            if event_type == "action_error":
                self._append_log(f"[ERROR] {payload['error']}")
                return

            if event_type == "blocked":
                self._set_status("Blocked")
                self._append_log(f"[BLOCKED] {payload['reason']}")
                return

            if event_type == "done":
                self._set_status("Completed")
                self._append_log(f"[DONE] {payload['message']}")
                return

            if event_type == "stopped":
                self._set_status("Stopped")
                self._append_log(f"[STOP] {payload['reason']}")
                return

            if event_type == "session_finished":
                self._set_status(_status_from_exit_code(payload["exit_code"]))
                self._append_log(
                    f"[INFO] session finished exit_code={payload['exit_code']} "
                    f"elapsed={payload['total_elapsed_sec']:.2f}s"
                )
                return

            if event_type == "session_error":
                self._set_status("Error")
                self._append_log(f"[ERROR] {payload['error']}")
                self._append_log(payload["traceback"])
                return

        def _update_screenshot(self, path: str) -> None:
            self._latest_screenshot_path = path
            pixmap = QtGui.QPixmap(path)
            if pixmap.isNull():
                self.screenshot_meta_label.setText(f"Path: {path}\nStatus: failed to load image")
                self.screenshot_label.setText(f"Failed to load screenshot:\n{path}")
                return

            scaled = pixmap.scaled(
                self.screenshot_label.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            self.screenshot_label.setPixmap(scaled)
            self.screenshot_label.setText("")

        def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
            super().resizeEvent(event)
            if self._latest_screenshot_path:
                self._update_screenshot(self._latest_screenshot_path)

        def _ask_confirmation(self, preview: str) -> bool:
            message = QtWidgets.QMessageBox(self)
            message.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            message.setWindowTitle("Confirm Action")
            message.setText("Approve the next desktop action?")
            message.setInformativeText(preview)
            message.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
            )
            message.setDefaultButton(QtWidgets.QMessageBox.StandardButton.No)
            return message.exec() == int(QtWidgets.QMessageBox.StandardButton.Yes)

        def _set_running(self, running: bool) -> None:
            self.start_button.setEnabled(not running)
            self.stop_button.setEnabled(running)
            self.config_path_edit.setEnabled(not running)
            self.task_edit.setEnabled(not running)
            self.model_edit.setEnabled(not running)
            self.base_url_edit.setEnabled(not running)
            self.api_key_edit.setEnabled(not running)
            self.api_key_toggle_button.setEnabled(not running)
            self.safety_mode_combo.setEnabled(not running)
            self.max_steps_spin.setEnabled(not running)
            self.step_delay_spin.setEnabled(not running)
            self.save_config_button.setEnabled(not running)

        def _toggle_api_key_visibility(self) -> None:
            if self.api_key_edit.echoMode() == QtWidgets.QLineEdit.EchoMode.Password:
                self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Normal)
                self.api_key_toggle_button.setText("Hide")
            else:
                self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
                self.api_key_toggle_button.setText("Show")

        def _set_status(self, status: str) -> None:
            formatted = _format_run_status(status)
            self._last_status = formatted
            self.status_label.setText(formatted)

        def _append_log(self, message: str) -> None:
            self.log_view.appendPlainText(message)
            scrollbar = self.log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        def _show_error(self, message: str) -> None:
            QtWidgets.QMessageBox.critical(self, "Desktop Agent GUI", message)

        def closeEvent(self, event: QtGui.QCloseEvent) -> None:
            if self._session is not None:
                self._session.request_stop()
            super().closeEvent(event)


def main() -> int:
    if _IMPORT_ERROR is not None:
        print(
            "PySide6 is required for the GUI. Install it with: pip install -e .[gui]",
            file=sys.stderr,
        )
        return 1

    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window._load_config_preview()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
