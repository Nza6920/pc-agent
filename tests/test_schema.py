import pytest

from desktop_agent.schemas import parse_decision


def test_parse_decision_valid():
    raw = """
    {
      "thought": "click start menu",
      "status": "in_progress",
      "confidence": 0.78,
      "reason_if_blocked": "",
      "action": { "type": "click", "x": 120, "y": 980, "button": "left" }
    }
    """
    decision = parse_decision(raw)
    assert decision.status == "in_progress"
    assert decision.action.type == "click"


def test_parse_decision_blocked_requires_reason():
    raw = """
    {
      "thought": "can't continue",
      "status": "blocked",
      "confidence": 0.2,
      "reason_if_blocked": "",
      "action": { "type": "wait", "seconds": 1 }
    }
    """
    with pytest.raises(ValueError):
        parse_decision(raw)


def test_parse_decision_press_action():
    raw = """
    {
      "thought": "confirm open",
      "status": "in_progress",
      "confidence": 0.9,
      "reason_if_blocked": "",
      "action": { "type": "press", "key": "enter", "presses": 1 }
    }
    """
    decision = parse_decision(raw)
    assert decision.action.type == "press"
