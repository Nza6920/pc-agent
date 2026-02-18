from __future__ import annotations

import argparse
import sys


def _configure_stdio_utf8() -> None:
    # Keep terminal I/O encoding consistent so Chinese task text is not mojibake.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _fix_task_mojibake(text: str) -> str:
    if not text:
        return text
    try:
        repaired = text.encode("gb18030").decode("utf-8")
    except Exception:
        return text
    # Use repaired text only when replacement characters are reduced.
    if repaired.count("\ufffd") <= text.count("\ufffd"):
        return repaired
    return text

def main() -> int:
    _configure_stdio_utf8()

    parser = argparse.ArgumentParser(description="Desktop Agent powered by mss + pyautogui + OpenAI")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    parser.add_argument("--task", default="", help="User task in natural language")
    args = parser.parse_args()

    from .app import run_agent
    from .config import load_config

    cfg = load_config(args.config)
    task = args.task.strip() or input("Enter your task: ").strip()
    task = _fix_task_mojibake(task)
    if not task:
        raise ValueError("Task cannot be empty.")
    return run_agent(task, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
