# 桌面自动化 Agent（mss + pyautogui + OpenAI SDK）

本项目实现了一个“看屏幕并操作电脑”的循环式 Agent，流程如下：

1. 截图主显示器（`mss`）
2. 把截图和任务发送给模型（OpenAI 兼容接口）
3. 模型返回下一步动作（严格 JSON）
4. 执行动作（`pyautogui`）
5. 重复直到任务完成或阻塞

支持通过 YAML 配置 `base_url`、`api_key`、`model`、运行参数、安全策略等。

## 功能特性

- OpenAI 兼容接口（可接入阿里云百炼等）
- 严格 JSON 决策协议（动作可校验）
- 模型坐标 `1000x1000` 到真实分辨率自动映射
- 安全模式（`auto` / `mixed` / `manual`）
- 中文等非 ASCII 文本输入优先使用粘贴策略（提升稳定性）
- 重复动作熔断，避免无限循环
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

- 操作系统：Windows 11
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

示例（阿里云百炼 OpenAI 兼容）：

```yaml
openai:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "YOUR_API_KEY_HERE"
  model: "qwen-vl-max-latest"
```

## 启动方式

推荐命令：

```powershell
desktop-agent --config config.yaml --task "打开记事本并输入 hello"
```

其他入口：

```powershell
python -m desktop_agent --config config.yaml --task "打开记事本并输入 hello"
python agent.py --config config.yaml --task "打开记事本并输入 hello"
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
- 会话日志：`runs/session.log`（JSON Lines）

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
