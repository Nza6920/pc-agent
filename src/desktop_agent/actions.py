from __future__ import annotations

from typing import Any

import pyperclip
import pyautogui


def map_coordinate(value: float, real_size: int, base: int) -> int:
    mapped = round((float(value) / float(base)) * float(real_size))
    return max(0, min(real_size - 1, mapped))


def map_point(
    x_ai: float,
    y_ai: float,
    width: int,
    height: int,
    base: int,
) -> tuple[int, int]:
    return map_coordinate(x_ai, width, base), map_coordinate(y_ai, height, base)


def _get_point(payload: dict[str, Any], width: int, height: int, base: int) -> tuple[int, int]:
    if "x" not in payload or "y" not in payload:
        raise ValueError("Action requires x and y")
    return map_point(payload["x"], payload["y"], width, height, base)


def perform_action(
    action_type: str,
    payload: dict[str, Any],
    width: int,
    height: int,
    base: int,
) -> str:
    pyautogui.PAUSE = 0.05

    if action_type == "move":
        x, y = _get_point(payload, width, height, base)
        duration = float(payload.get("duration", 0.2))
        pyautogui.moveTo(x, y, duration=duration)
        return f"move ({x},{y})"

    if action_type == "click":
        x, y = _get_point(payload, width, height, base)
        button = str(payload.get("button", "left"))
        pyautogui.click(x=x, y=y, button=button)
        return f"click {button} ({x},{y})"

    if action_type == "double_click":
        x, y = _get_point(payload, width, height, base)
        button = str(payload.get("button", "left"))
        pyautogui.doubleClick(x=x, y=y, button=button)
        return f"double_click {button} ({x},{y})"

    if action_type == "right_click":
        x, y = _get_point(payload, width, height, base)
        pyautogui.rightClick(x=x, y=y)
        return f"right_click ({x},{y})"

    if action_type == "scroll":
        amount = int(payload.get("amount", -300))
        if "x" in payload and "y" in payload:
            x, y = _get_point(payload, width, height, base)
            pyautogui.moveTo(x, y, duration=0.1)
        pyautogui.scroll(amount)
        return f"scroll {amount}"

    if action_type == "type_text":
        text = str(payload.get("text", ""))
        if not text:
            raise ValueError("type_text requires non-empty text")
        interval = float(payload.get("interval", 0.01))
        # Use paste for non-ASCII text (e.g. Chinese) because direct typing is often unreliable with IME.
        if not text.isascii():
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            return f"type_text paste len={len(text)}"
        pyautogui.write(text, interval=interval)
        return f"type_text write len={len(text)}"

    if action_type == "hotkey":
        keys = payload.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ValueError("hotkey requires keys list")
        pyautogui.hotkey(*[str(k) for k in keys])
        return f"hotkey {'+'.join(str(k) for k in keys)}"

    if action_type == "press":
        key = str(payload.get("key", "")).strip()
        if not key:
            raise ValueError("press requires key")
        presses = max(1, int(payload.get("presses", 1)))
        interval = max(0.0, float(payload.get("interval", 0.0)))
        pyautogui.press(key, presses=presses, interval=interval)
        return f"press {key} x{presses}"

    if action_type == "wait":
        seconds = max(0.0, float(payload.get("seconds", 1.0)))
        pyautogui.sleep(seconds)
        return f"wait {seconds}s"

    if action_type == "finish":
        return f"finish: {str(payload.get('message', 'done'))}"

    raise ValueError(f"Unsupported action type: {action_type}")
