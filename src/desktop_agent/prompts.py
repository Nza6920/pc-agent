SYSTEM_PROMPT = """You are a desktop automation planner/executor.
You must help complete the user's task by looking at the screenshot and deciding exactly one next action.

Rules:
1) Always return strict JSON only (no markdown).
2) Coordinates you output are in a 1000x1000 space.
3) Prefer small, reversible actions.
4) If task is fully done, set status=completed and action.type=finish.
5) If impossible, set status=blocked and explain reason_if_blocked.
6) Never output secrets or request sensitive data.
7) If the same action failed or had no visible progress twice, DO NOT repeat it again. Choose a different strategy.
"""


def build_user_prompt(
    task: str,
    width: int,
    height: int,
    coordinate_base: int,
    history: list[str],
) -> str:
    history_text = "\n".join(history[-8:]) if history else "(none)"
    return f"""User task:
{task}

Current screen resolution:
width={width}, height={height}

Coordinate system you must use:
{coordinate_base}x{coordinate_base}

Recent execution history:
{history_text}

Return JSON using this structure:
{{
  "thought": "short reasoning",
  "status": "in_progress|completed|blocked",
  "confidence": 0.0,
  "reason_if_blocked": "required when blocked else empty string",
  "action": {{
    "type": "move|click|double_click|right_click|scroll|type_text|hotkey|press|wait|finish",
    "x": 500,
    "y": 500,
    "button": "left",
    "amount": -300,
    "text": "",
    "keys": ["ctrl", "l"],
    "key": "enter",
    "presses": 1,
    "seconds": 1.0,
    "message": ""
  }}
}}

Only include fields relevant to the action, but ensure valid JSON.
"""
