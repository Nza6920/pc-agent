# Desktop Automation Agent (mss + pyautogui + OpenAI SDK)

This project implements a loop-based desktop agent that "sees the screen and operates the computer":

1. Capture the primary monitor (`mss`)
2. Send screenshot + task to the model (OpenAI-compatible API)
3. Model returns exactly one next action (strict JSON)
4. Execute action (`pyautogui`)
5. Repeat until completed or blocked

You can configure `base_url`, `api_key`, `model`, runtime options, and safety policy via YAML.
Current version supports **Windows 11 only**.

## Features

- OpenAI-compatible API (including Alibaba Cloud Bailian compatible endpoint)
- Strict JSON decision schema (action validation)
- Automatic coordinate mapping from `1000x1000` to real resolution
- Safety modes (`auto` / `mixed` / `manual`)
- Non-ASCII text input uses paste-first strategy for better stability
- Repetition guards to avoid infinite loops
- Phase-based execution + semantic repeat guard
- Basic unit tests for config, coordinate mapping, and output parsing

## Project Structure

```text
pc-agent/
├─ src/
│  └─ desktop_agent/
│     ├─ __main__.py      # entry for python -m desktop_agent
│     ├─ cli.py           # CLI argument parsing
│     ├─ app.py           # main agent loop
│     ├─ config.py        # config loading and validation
│     ├─ llm.py           # model client wrapper
│     ├─ prompts.py       # prompt templates
│     ├─ schemas.py       # model output schema validation
│     ├─ screen.py        # screenshots and resolution helpers
│     ├─ actions.py       # mouse/keyboard actions
│     └─ safety.py        # safety confirmation policy
├─ tests/
├─ config.yaml.example
├─ config.yaml            # local config (gitignored)
├─ pyproject.toml
├─ requirements.txt
└─ agent.py               # compatibility entry
```

## Environment

- OS: Windows 11 (only)
- Python: 3.10+ (recommended 3.11/3.12)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

## Configuration

1. Copy template:

```powershell
Copy-Item config.yaml.example config.yaml
```

2. Fill required fields:

- `openai.base_url`
- `openai.api_key`
- `openai.model`

Recommended model: `qwen3-vl-flash`

Full example:

```yaml
openai: # model API config
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1" # OpenAI-compatible endpoint
  api_key: "YOUR_API_KEY_HERE" # replace with your real key
  model: "qwen3-vl-flash" # vision-capable model (recommended)
  timeout_sec: 60 # request timeout in seconds

runtime: # runtime config
  max_steps: 40 # max steps per task
  step_delay_sec: 0.4 # fixed delay after each step
  screenshot_path: "./runs/latest.png" # latest screenshot path (overwritten)
  log_path: "./runs/session.log" # session log path (JSONL)
  llm_trace_enabled: true # write prompt/response traces
  llm_trace_dir: "./runs/llm_traces" # trace output directory
  image_format: "jpeg" # jpeg | png
  image_max_long_edge: 1280 # image resize limit for speed/cost
  image_jpeg_quality: 70 # [1,95], only for jpeg
  guard_exact_repeat_threshold: 5 # block exact repeated action+payload
  guard_semantic_repeat_threshold: 4 # block semantic repeated actions
  guard_phase_stagnant_threshold: 1000000 # effectively disabled with very large value
  guard_type_text_focus: true # block type_text if focus not prepared

safety: # safety interaction config
  mode: "mixed" # auto | mixed | manual
  confirm_actions: # actions that require confirmation in mixed/manual
    - "type_text"
    - "hotkey"
    - "right_click"
    - "double_click"

display: # display and coordinate mapping
  monitor: "primary" # only primary monitor is supported
  coordinate_base: 1000 # model coordinate base (1000x1000)
```

## Run

Recommended:

```powershell
desktop-agent --config config.yaml --task "Open NetEase Cloud Music and play My Favorites"
```

Other entries:

```powershell
python -m desktop_agent --config config.yaml --task "Open NetEase Cloud Music and play My Favorites"
python agent.py --config config.yaml --task "Open NetEase Cloud Music and play My Favorites"
```

Without `--task`, CLI enters interactive mode.

## Runtime Loop

Each iteration:

1. Capture screenshot
2. Ask model for one action
3. Execute action (with confirmations in mixed mode)
4. Continue to next step

## Coordinate Mapping

Model outputs coordinates in `1000x1000`, then mapped to `(W, H)`:

- `x_real = round((x_ai / 1000) * W)`
- `y_real = round((y_ai / 1000) * H)`

Coordinates are clamped to screen bounds.

## Supported Actions

- `move`
- `click`
- `double_click`
- `right_click`
- `scroll`
- `type_text`
- `hotkey`
- `press`
- `wait`
- `finish`

## Safety Modes

- `auto`: no confirmation
- `mixed`: confirmation for high-risk actions (recommended)
- `manual`: confirm every step

High-risk action list is controlled by `safety.confirm_actions`.

## Artifacts and Logs

- Latest screenshot: `runs/latest.png`
- Session log: `runs/session.log` (JSONL, includes `session_id`)
- LLM traces: `runs/llm_traces/` (one JSON per step, includes full prompts + raw model output)
- Timing fields: `capture_sec`, `encode_sec`, `llm_sec`, `action_sec`, `sleep_sec`

Analyze logs:

```powershell
python scripts/analyze_session_log.py --log runs/session.log
python scripts/analyze_session_log.py --log runs/session.log --latest-session
python scripts/analyze_session_log.py --log runs/session.log --session-id 39d37e99b95449bfb9b7ee0a1db1cb68
```

## FAQ

### 1. `Missing required config field`

`config.yaml` is missing required keys (`base_url/api_key/model`).

### 2. Repeating same action

Usually focus/IME/UI-state issue. Try:

- simplify task first
- increase `runtime.step_delay_sec` (e.g. `0.8`)
- use a stronger vision model

### 3. Unstable Chinese input

For non-ASCII text, agent prefers clipboard paste (`Ctrl+V`) over character-by-character typing.

### 4. Tests cannot run

Install pytest if missing:

```powershell
pip install pytest
```

## Safety Notes

- Desktop automation can misoperate; test in a controlled environment first.
- Never commit real secrets in `config.yaml`.
