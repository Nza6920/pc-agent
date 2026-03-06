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
        self.timeout_sec = timeout_sec
        self.temperature = 0.2
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_sec)

    def request_decision(self, user_prompt: str, screenshot_b64: str, image_mime_type: str) -> LLMCallResult:
        trace: dict[str, Any] = {
            "request": {
                "model": self.model,
                "temperature": self.temperature,
                "timeout_sec": self.timeout_sec,
                "message_roles": ["system", "user"],
                "user_content_types": ["text", "image_url"],
            },
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": user_prompt,
            "image_mime_type": image_mime_type,
            "image_b64_length": len(screenshot_b64),
            "attempts": [],
        }

        raw, response_meta = self._complete(user_prompt, screenshot_b64, image_mime_type)
        trace["attempts"].append(
            {
                "attempt": 1,
                "repair": False,
                "response_meta": response_meta,
                "raw_response": raw,
            }
        )
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
            raw_repair, repair_response_meta = self._complete(repair_prompt, screenshot_b64, image_mime_type)
            trace["attempts"].append(
                {
                    "attempt": 2,
                    "repair": True,
                    "repair_error": str(first_err),
                    "repair_prompt": repair_prompt,
                    "response_meta": repair_response_meta,
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

    def _response_meta(self, response: Any) -> dict[str, Any]:
        choice = response.choices[0] if getattr(response, "choices", None) else None
        message = getattr(choice, "message", None)
        usage = getattr(response, "usage", None)
        content = getattr(message, "content", None)
        refusal = getattr(message, "refusal", None)
        tool_calls = getattr(message, "tool_calls", None)
        audio = getattr(message, "audio", None)
        annotations = getattr(message, "annotations", None)

        return {
            "id": getattr(response, "id", None),
            "model": getattr(response, "model", None),
            "created": getattr(response, "created", None),
            "service_tier": getattr(response, "service_tier", None),
            "system_fingerprint": getattr(response, "system_fingerprint", None),
            "finish_reason": getattr(choice, "finish_reason", None),
            "role": getattr(message, "role", None),
            "content_type": type(content).__name__ if content is not None else None,
            "refusal": refusal,
            "has_tool_calls": bool(tool_calls),
            "tool_call_count": len(tool_calls) if tool_calls else 0,
            "has_audio": audio is not None,
            "annotation_count": len(annotations) if annotations else 0,
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
            },
        }

    def _complete(self, user_prompt: str, screenshot_b64: str, image_mime_type: str) -> tuple[str, dict[str, Any]]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
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
        response_meta = self._response_meta(response)
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Model returned empty content")
        return content.strip(), response_meta
