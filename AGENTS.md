# Repository Guidelines

## Project Structure & Module Organization

Core code lives in `src/desktop_agent/`. Use `cli.py` and `gui.py` for user entry points, `app.py` for the shared runner loop, `config.py` for YAML loading/validation, and `actions.py`, `screen.py`, `llm.py`, and `safety.py` for execution subsystems. Tests live in `tests/` and follow the runtime modules closely. Supporting docs are in `docs/`, and utility scripts such as log analysis live in `scripts/`.

## Build, Test, and Development Commands

- `python -m venv .venv` then `.venv\Scripts\activate`: create and activate a local environment on Windows.
- `pip install -e .[dev]`: install the package plus test dependencies.
- `pip install -e .[gui]`: install optional GUI dependencies (`PySide6`).
- `python -m pytest` or `.\.venv\Scripts\python.exe -m pytest`: run the full test suite.
- `desktop-agent --config config.yaml --task "..."`: run the CLI agent.
- `python -m desktop_agent.gui` or `desktop-agent-gui`: launch the GUI.

## Coding Style & Naming Conventions

Follow existing Python style: 4-space indentation, type hints where practical, `snake_case` for functions/modules, `PascalCase` for classes, and short, focused helper functions. Keep comments sparse and explanatory, not descriptive of obvious syntax. Match the repository’s current pattern of dataclasses for structured state and small module-level helpers for shared logic.

When reading or rewriting repository text files, prefer UTF-8 explicitly to avoid mojibake in Markdown, YAML, and docs.

## Testing Guidelines

This project uses `pytest`. Add tests under `tests/` with names like `test_config.py` or `test_app_runner.py`, and name test functions `test_<behavior>()`. Prefer focused unit tests around config parsing, event flow, guards, and coordinate mapping. Run `python -m pytest` before submitting changes.

## Commit & Pull Request Guidelines

Recent commits use short, imperative subjects such as `Add PySide6 GUI runner` and `Improve GUI run status feedback`. Keep commit titles concise and action-oriented. PRs should describe the user-visible change, note any config or safety implications, link related issues when applicable, and include screenshots for GUI changes.

## Security & Configuration Tips

Do not commit real secrets in `config.yaml`; use `config.yaml.example` as the template. Keep desktop automation changes safe by testing in a controlled environment, especially for `mixed` and `manual` safety flows.
