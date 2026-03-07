# 桌面自动化 Agent（mss + pyautogui + OpenAI SDK）

[English Version](README_EN.md)

本项目实现了一个“看屏幕并操作电脑”的循环式桌面 Agent，流程如下：

1. 截图主显示器（`mss`）
2. 把截图和任务发送给模型（OpenAI 兼容接口）
3. 模型返回下一步动作（严格 JSON）
4. 执行动作（`pyautogui`）
5. 重复直到任务完成或被阻断

你可以通过 YAML 配置 `base_url`、`api_key`、`model`、运行参数和安全策略。
当前版本仅支持 **Windows 11**。

## 功能特性

- OpenAI 兼容接口（可接入阿里云百炼等）
- 模型坐标 `1000x1000` 自动映射到真实分辨率
- 安全模式支持 `auto` / `mixed` / `manual`
- 重复动作保护，避免无效循环
- 分阶段执行和语义重复阻断

## 项目结构

```text
pc-agent/
├─ src/
│  └─ desktop_agent/
│     ├─ __main__.py      # python -m desktop_agent 入口
│     ├─ cli.py           # CLI 参数解析
│     ├─ app.py           # Agent 主循环
│     ├─ gui.py           # GUI 入口（PySide6）
│     ├─ config.py        # 配置加载与校验
│     ├─ llm.py           # 模型调用封装
│     ├─ prompts.py       # 提示词模板
│     ├─ schemas.py       # 模型返回结构校验
│     ├─ screen.py        # 截图与分辨率处理
│     ├─ actions.py       # 鼠标键盘动作执行
│     └─ safety.py        # 安全确认策略
├─ tests/                 # 单元测试
├─ config.yaml.example    # 配置模板
├─ config.yaml            # 本地配置（已加入 .gitignore）
├─ pyproject.toml
├─ requirements.txt
└─ agent.py               # 兼容入口
```

## 环境准备

- 操作系统：Windows 11（当前仅支持此系统）
- Python：3.10+（建议 3.11 / 3.12）

安装：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

如果要使用 GUI：

```powershell
pip install -e .[gui]
```

## 配置说明

1. 复制模板：

```powershell
Copy-Item config.yaml.example config.yaml
```

2. 至少填写以下字段：

- `openai.base_url`
- `openai.api_key`
- `openai.model`

推荐模型：`qwen3-vl-flash`

完整示例：

```yaml
openai:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "YOUR_API_KEY_HERE"
  model: "qwen3-vl-flash"
  timeout_sec: 60

runtime:
  max_steps: 40
  step_delay_sec: 0.4
  screenshot_path: "./runs/latest.png"
  screenshot_archive_dir: "./runs/screenshots"
  log_path: "./runs/session.log"
  llm_trace_enabled: true
  llm_trace_dir: "./runs/llm_traces"
  image_format: "jpeg"
  image_max_long_edge: 1280
  image_jpeg_quality: 70
  guard_exact_repeat_threshold: 5
  guard_semantic_repeat_threshold: 4
  guard_phase_stagnant_threshold: 1000000
  guard_type_text_focus: true

safety:
  mode: "mixed"
  confirm_actions:
    - "type_text"
    - "hotkey"
    - "right_click"
    - "double_click"

display:
  monitor: "primary"
  coordinate_base: 1000
```

## 启动方式

推荐 CLI 命令：

```powershell
desktop-agent --config config.yaml --task "打开网易云音乐播放我的喜欢"
```

其他 CLI 入口：

```powershell
python -m desktop_agent --config config.yaml --task "打开网易云音乐播放我的喜欢"
python agent.py --config config.yaml --task "打开网易云音乐播放我的喜欢"
```

不传 `--task` 时，CLI 会进入交互式输入。

GUI 入口：

```powershell
desktop-agent-gui
python -m desktop_agent.gui
```

## GUI

GUI 基于 PySide6，底层复用和 CLI 相同的 `AgentRunner` 执行器。

当前 GUI 支持：

- 自动加载项目根目录下的 `config.yaml`，也可手动切换配置文件
- 首次使用 GUI 且本地不存在 `config.yaml` 时，会自动从 `config.yaml.example` 创建
- 直接在窗口里编辑并保存常用配置
- 在后台线程运行任务，不阻塞界面
- 预览最新截图和归档截图路径
- 查看事件日志、`session_id`、`step`、`phase` 和运行状态
- 通过弹窗批准或拒绝高风险动作

GUI 当前可编辑的配置项：

- `openai.model`
- `openai.base_url`
- `openai.api_key`
- `runtime.max_steps`
- `runtime.step_delay_sec`
- `safety.mode`

GUI 当前行为：

- `Run Status` 表示整体运行状态，例如 `Running`、`Blocked`、`Completed`、`Stopped`
- `Phase` 表示执行阶段，例如 `Observe`、`Execute`、`Finalize`
- 运行中会锁定配置输入，避免边跑边改
- `API Key` 默认隐藏，可通过按钮切换显示 / 隐藏
- 如果默认配置文件缺失，GUI 会自动按模板生成后再加载

GUI 当前限制：

- 仅支持 Windows
- 只有部分配置项可在 GUI 中直接编辑，其余项仍然从 YAML 读取
- `Phase` 不等于最终结果，一个任务可能在 `Execute` 阶段被 `Blocked`
- 当前还没有单独打包 GUI 可执行安装包，需要通过 Python 环境启动

## 运行机制

每一轮会执行：

1. 截图
2. 请求模型返回一个动作
3. 执行动作（`mixed` 模式下高风险动作需要确认）
4. 进入下一轮

输出示例：

```text
[STEP 1] thought=... status=in_progress action=click {...}
```

## 坐标映射规则

模型输出坐标基于 `1000x1000`，程序会映射到真实分辨率 `(W, H)`：

- `x_real = round((x_ai / 1000) * W)`
- `y_real = round((y_ai / 1000) * H)`

并自动裁剪到屏幕范围内。

## 支持动作

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

## 安全模式

- `auto`：全自动，无确认
- `mixed`：仅高风险动作确认（推荐）
- `manual`：每一步都确认

高风险动作列表由 `safety.confirm_actions` 控制。

## 产物与日志

- 最新截图：`runs/latest.png`
- 会话日志：`runs/session.log`（JSONL，包含 `session_id`）
- LLM 调用追踪：`runs/llm_traces/`（每步一个 JSON，包含完整 prompt 和原始模型输出）
- 耗时字段：`capture_sec`、`encode_sec`、`llm_sec`、`action_sec`、`sleep_sec`

日志分析：

```powershell
python scripts/analyze_session_log.py --log runs/session.log
python scripts/analyze_session_log.py --log runs/session.log --latest-session
python scripts/analyze_session_log.py --log runs/session.log --session-id 39d37e99b95449bfb9b7ee0a1db1cb68
```

## 常见问题

### 1. 报错 `Missing required config field`

`config.yaml` 缺少必填字段，请补齐 `base_url / api_key / model`。

### 2. 模型反复执行同一步

通常是焦点、输入法或界面状态问题。可尝试：

- 先把任务拆简单，缩短链路
- 调大 `runtime.step_delay_sec`，例如 `0.8`
- 使用更强的视觉模型

### 3. 中文输入不稳定

对于非 ASCII 文本，Agent 会优先走粘贴（`Ctrl+V`），比逐字输入更稳定。

### 4. 无法运行测试

如果缺少 `pytest`：

```powershell
pip install pytest
```

## 安全建议

- 桌面自动化可能触发误操作，请先在可控环境试跑
- 不要提交包含真实密钥的 `config.yaml`
