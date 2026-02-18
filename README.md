# 桌面自动化 Agent（mss + pyautogui + OpenAI SDK）

本项目实现了一个“看屏幕并操作电脑”的循环式 Agent，流程如下：

1. 截图主显示器（`mss`）
2. 把截图和任务发送给模型（OpenAI 兼容接口）
3. 模型返回下一步动作（严格 JSON）
4. 执行动作（`pyautogui`）
5. 重复直到任务完成或阻塞

支持通过 YAML 配置 `base_url`、`api_key`、`model`、运行参数、安全策略等。
当前版本仅支持 Windows 11。

## 功能特性

- OpenAI 兼容接口（可接入阿里云百炼等）
- 严格 JSON 决策协议（动作可校验）
- 模型坐标 `1000x1000` 到真实分辨率自动映射
- 安全模式（`auto` / `mixed` / `manual`）
- 中文等非 ASCII 文本输入优先使用粘贴策略（提升稳定性）
- 重复动作熔断，避免无限循环
- 阶段状态机（打开应用/输入内容/保存文件/收尾）与语义重复熔断，降低绕圈概率
- 基础单测覆盖：配置、坐标映射、输出解析

## 项目结构

```text
pc-agent/
├─ src/
│  └─ desktop_agent/
│     ├─ __main__.py      # python -m desktop_agent 入口
│     ├─ cli.py           # CLI 参数解析
│     ├─ app.py           # Agent 主循环
│     ├─ config.py        # 配置加载与校验
│     ├─ llm.py           # 模型调用封装
│     ├─ prompts.py       # 提示词模板
│     ├─ schemas.py       # 模型返回结构校验
│     ├─ screen.py        # 截图与分辨率
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
- Python：3.10+（建议 3.11/3.12）

安装步骤：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

## 配置说明

1. 复制模板：

```powershell
Copy-Item config.yaml.example config.yaml
```

2. 编辑 `config.yaml`，至少填写：

- `openai.base_url`
- `openai.api_key`
- `openai.model`
- 其他参数可直接使用默认值
- 推荐使用模型：`qwen3-vl-flash`

完整示例（与 `config.yaml.example` 同步，阿里云百炼 OpenAI 兼容）：

```yaml
openai: # 大模型调用配置
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1" # OpenAI 兼容接口地址（阿里云百炼）
  api_key: "YOUR_API_KEY_HERE" # API Key（请替换为你的真实密钥）
  model: "qwen3-vl-flash" # 使用的模型名称（需支持图像输入，推荐：qwen3-vl-flash）
  timeout_sec: 60 # 单次模型请求超时时间（秒）

runtime: # Agent 运行时配置
  max_steps: 40 # 单次任务最多执行多少步，超过后停止
  step_delay_sec: 0.4 # 每一步执行后的固定等待时间（秒）
  screenshot_path: "./runs/latest.png" # 最新截图保存路径（会被覆盖）
  log_path: "./runs/session.log" # 会话日志文件路径（JSONL）
  llm_trace_enabled: true # 是否记录每步完整提示词/模型返回 trace
  llm_trace_dir: "./runs/llm_traces" # trace 输出目录
  image_format: "jpeg" # 截图格式：jpeg | png
  image_max_long_edge: 1280 # 截图最长边缩放上限（像素），用于提速与降成本
  image_jpeg_quality: 70 # JPEG 压缩质量 [1,95]，仅 image_format=jpeg 时生效
  guard_exact_repeat_threshold: 5 # 完全相同动作+参数连续重复达到该值后阻断
  guard_semantic_repeat_threshold: 4 # 语义相近动作（如同区域重复点击/同文本重复输入）达到该值后阻断
  guard_phase_stagnant_threshold: 1000000 # 阶段停滞阻断阈值；设很大值近似关闭，0 视为关闭
  guard_type_text_focus: true # 输入焦点守卫：无焦点准备时禁止直接 type_text

safety: # 安全交互配置
  mode: "mixed" # 执行模式：auto(全自动) | mixed(部分确认) | manual(全部确认)
  confirm_actions: # 在 mixed/manual 下需要人工确认的动作类型列表
    - "type_text" # 输入文本
    - "hotkey" # 组合键
    - "right_click" # 右键点击
    - "double_click" # 双击

display: # 显示与坐标映射配置
  monitor: "primary" # 目标显示器，目前仅支持 primary
  coordinate_base: 1000 # 模型坐标基准边长（1000 表示模型输出 1000x1000 坐标系）
```

## 启动方式

推荐命令：

```powershell
desktop-agent --config config.yaml --task "打开网易云音乐播放我的喜欢"
```

其他入口：

```powershell
python -m desktop_agent --config config.yaml --task "打开网易云音乐播放我的喜欢"
python agent.py --config config.yaml --task "打开网易云音乐播放我的喜欢"
```

不传 `--task` 时会进入交互输入。

## 运行机制

每一轮会执行：

1. 截图
2. 模型思考并返回一个动作
3. 执行动作（混合模式下高风险动作需确认）
4. 进入下一轮

输出示例：

```text
[STEP 1] thought=... status=in_progress action=click {...}
```

## 坐标映射规则

模型输出坐标基于 `1000x1000`，程序映射到真实分辨率 `(W, H)`：

- `x_real = round((x_ai / 1000) * W)`
- `y_real = round((y_ai / 1000) * H)`

并自动裁剪到屏幕边界范围内。

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

默认高风险动作列表由 `safety.confirm_actions` 控制。

## 产物与日志

- 最新截图：`runs/latest.png`
- 会话日志：`runs/session.log`（JSON Lines，每条记录包含 `session_id`）
- LLM 调用追踪：`runs/llm_traces/`（每步一个 JSON，文件名带 `session_id`，含完整 system/user prompt 与原始模型返回）
- 分项耗时字段：`capture_sec`、`encode_sec`、`llm_sec`、`action_sec`、`sleep_sec`

日志分析脚本：

```powershell
python scripts/analyze_session_log.py --log runs/session.log
```

按会话分析（需要日志中已包含 `session_id`）：

```powershell
python scripts/analyze_session_log.py --log runs/session.log --latest-session
python scripts/analyze_session_log.py --log runs/session.log --session-id 39d37e99b95449bfb9b7ee0a1db1cb68
```

可在配置中关闭/调整 LLM 追踪：

```yaml
runtime:
  llm_trace_enabled: true
  llm_trace_dir: "./runs/llm_traces"
```

## 常见问题

### 1. 报错 `Missing required config field`

`config.yaml` 缺少必填字段，请补齐 `base_url/api_key/model`。

### 2. 模型反复执行同一步

通常是焦点或输入法问题。可尝试：

- 降低任务复杂度，先验证点击链路
- 调大 `runtime.step_delay_sec`（如 `0.8`）
- 使用支持视觉能力更强的模型

### 3. 中文输入不稳定

当前实现对非 ASCII 文本会优先走剪贴板粘贴（`Ctrl+V`），比逐字输入更稳定。

### 4. 无法运行测试

若提示缺少 pytest：

```powershell
pip install pytest
```

## 安全建议

- 桌面自动化可能触发误操作，请先在可控环境试跑。
- 不要提交包含真实密钥的 `config.yaml`。
