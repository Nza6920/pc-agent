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
8) Follow the current execution phase and allowed action list from user prompt.
9) Do not regress to previous phases once a later phase has started.
10) If no visible progress for 2 consecutive steps, switch strategy immediately.
11) If the file/content already appears saved (e.g., save confirmed or overwrite confirmed), immediately return completed+finish.
12) After save success signals, DO NOT type more content and DO NOT repeat save flow.
13) Coordinates must be valid JSON fields: use `"x": number` and `"y": number` separately. Never use forms like `"x": 100, 200`.
"""


def build_user_prompt(
    task: str,
    width: int,
    height: int,
    coordinate_base: int,
    history: list[str],
    phase: str,
    allowed_actions: list[str],
    phase_note: str,
) -> str:
    history_text = "\n".join(history[-8:]) if history else "(none)"
    allowed_text = ", ".join(allowed_actions)
    return f"""User task:
{task}

Current screen resolution:
width={width}, height={height}

Coordinate system you must use:
{coordinate_base}x{coordinate_base}

Current execution phase:
{phase}
Phase guidance:
{phase_note}
Allowed actions in this phase:
{allowed_text}

Recent execution history:
{history_text}

Completion policy:
- If you see evidence that task is already completed, return:
  status="completed" and action.type="finish".
- Do not continue editing or saving after completion signals.
- Avoid repeated cycles like "open file menu -> save as -> save -> overwrite" when already done.
- Coordinate format must be strict JSON: if action needs position, include both `"x"` and `"y"` keys explicitly.
- Invalid example (forbidden): `"x": 107, 892`
- Valid example: `"x": 107, "y": 892`

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
