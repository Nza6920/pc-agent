from __future__ import annotations

import argparse

def main() -> int:
    parser = argparse.ArgumentParser(description="Desktop Agent powered by mss + pyautogui + OpenAI")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    parser.add_argument("--task", default="", help="User task in natural language")
    args = parser.parse_args()

    from .app import run_agent
    from .config import load_config

    cfg = load_config(args.config)
    task = args.task.strip() or input("Enter your task: ").strip()
    if not task:
        raise ValueError("Task cannot be empty.")
    return run_agent(task, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
