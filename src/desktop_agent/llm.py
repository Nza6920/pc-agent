from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .prompts import SYSTEM_PROMPT
from .schemas import LLMDecision, parse_decision


@dataclass
class LLMCallResult:
    decision: LLMDecision
    trace: dict[str, Any]


class LLMResponseParseError(ValueError):
    def __init__(self, message: str, trace: dict[str, Any]) -> None:
        super().__init__(message)
        self.trace = trace


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_sec: int = 60) -> None:
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_sec)

    def request_decision(self, user_prompt: str, screenshot_b64: str, image_mime_type: str) -> LLMCallResult:
        trace: dict[str, Any] = {
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": user_prompt,
            "image_mime_type": image_mime_type,
            "image_b64_length": len(screenshot_b64),
            "attempts": [],
        }

        raw = self._complete(user_prompt, screenshot_b64, image_mime_type)
        trace["attempts"].append({"attempt": 1, "repair": False, "raw_response": raw})
        try:
            decision = parse_decision(raw)
            trace["parsed_on_attempt"] = 1
            return LLMCallResult(decision=decision, trace=trace)
        except Exception as first_err:
            repair_prompt = (
                user_prompt
                + "\n\nYour previous output was invalid JSON for this schema. "
                + f"Error: {first_err}. Return strict JSON only."
            )
            raw_repair = self._complete(repair_prompt, screenshot_b64, image_mime_type)
            trace["attempts"].append(
                {
                    "attempt": 2,
                    "repair": True,
                    "repair_error": str(first_err),
                    "repair_prompt": repair_prompt,
                    "raw_response": raw_repair,
                }
            )
            try:
                decision = parse_decision(raw_repair)
                trace["parsed_on_attempt"] = 2
                return LLMCallResult(decision=decision, trace=trace)
            except Exception as second_err:
                trace["parsed_on_attempt"] = None
                trace["parse_error"] = str(second_err)
                raise LLMResponseParseError("Model output is not valid JSON after retry", trace) from second_err

    def _complete(self, user_prompt: str, screenshot_b64: str, image_mime_type: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{image_mime_type};base64,{screenshot_b64}"},
                        },
                    ],
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Model returned empty content")
        return content.strip()
