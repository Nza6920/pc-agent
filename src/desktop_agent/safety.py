from __future__ import annotations


def needs_confirmation(action_type: str, mode: str, confirm_actions: list[str]) -> bool:
    if mode == "auto":
        return False
    if mode == "manual":
        return True
    return action_type in set(confirm_actions)


def confirm_action_cli(action_summary: str) -> bool:
    answer = input(f"[CONFIRM] Execute action: {action_summary}? (y/N): ").strip().lower()
    return answer in {"y", "yes"}
