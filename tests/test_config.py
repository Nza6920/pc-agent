import pytest

from desktop_agent.config import load_config


def test_load_config_missing_api_key():
    from pathlib import Path

    cfg_file = Path("runs/test_config_missing_key.yaml")
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(
        """
openai:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4.1"
        """.strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_config(str(cfg_file))
