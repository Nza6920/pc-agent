from __future__ import annotations

from openai import OpenAI

from .prompts import SYSTEM_PROMPT
from .schemas import LLMDecision, parse_decision


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_sec: int = 60) -> None:
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_sec)

    def request_decision(self, user_prompt: str, screenshot_b64: str) -> LLMDecision:
        raw = self._complete(user_prompt, screenshot_b64)
        try:
            return parse_decision(raw)
        except Exception as first_err:
            repair_prompt = (
                user_prompt
                + "\n\nYour previous output was invalid JSON for this schema. "
                + f"Error: {first_err}. Return strict JSON only."
            )
            raw_repair = self._complete(repair_prompt, screenshot_b64)
            return parse_decision(raw_repair)

    def _complete(self, user_prompt: str, screenshot_b64: str) -> str:
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
                            "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                        },
                    ],
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Model returned empty content")
        return content.strip()
