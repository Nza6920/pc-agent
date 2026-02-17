# Project Structure

```text
pc-agent/
├─ src/
│  └─ desktop_agent/
│     ├─ __init__.py
│     ├─ __main__.py
│     ├─ cli.py          # CLI entrypoint
│     ├─ app.py          # Agent loop orchestration
│     ├─ config.py       # YAML config schema/load/validation
│     ├─ llm.py          # OpenAI-compatible client wrapper
│     ├─ prompts.py      # Prompt templates and response contract
│     ├─ schemas.py      # Model output parsing/validation
│     ├─ screen.py       # Screenshot and screen resolution
│     ├─ actions.py      # Mouse/keyboard execution and coord mapping
│     └─ safety.py       # Safety confirmation policy
├─ tests/
│  ├─ conftest.py
│  ├─ test_config.py
│  ├─ test_mapping.py
│  └─ test_schema.py
├─ docs/
│  └─ PROJECT_STRUCTURE.md
├─ config.yaml
├─ pyproject.toml
├─ requirements.txt
├─ README.md
├─ RUN_GUIDE.md
└─ agent.py              # backward-compatible wrapper entrypoint
```

## Design Notes

- Uses `src/` layout to avoid accidental imports from repository root.
- Keeps runtime logic and CLI parsing separated (`app.py` vs `cli.py`).
- Enforces one canonical implementation under `src/desktop_agent`.
- Root modules are kept as compatibility shims for existing commands.
