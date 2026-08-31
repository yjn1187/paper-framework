# opencode & codex 使用详解（paper-framework）

本文说明本框架**实际使用** `opencode` 和 `codex` 的命令、提示词与数据解析方式，帮助你理解
「给一篇论文，网页/CLI 是怎么调用 Agent 生成解读的」。所有命令与参数均与 `scripts/*.py` 中的实现一致。

---

## 0. 总览：内容从哪里来

```
论文(arXiv链接/本地PDF)
      │
      │  ① 拼装提示词  build_message()  =  prompt文件 + 论文 + 目标路径
      ▼
   LLM Agent (opencode 或 codex)        ② 用 subprocess 启动，读事件流
      │
      │  ③ 逐行解析 NDJSON/JSONL
      ▼
   日志（🧠思考 / $命令 / ⚠出错 / ✎写盘） + content.json 落盘
      │
      │  ④ load_versions() 聚合各版本
      ▼
   render.py  ⑤  →  papers/<id>/index.html（含主题/版本/原文切换）
```

关键点：**Agent 不是把 JSON 吐在聊天里，而是直接写盘 `content/<id>__<version>.json`**。
框架一方面从输出事件流抽取正文作为候选，另一方面检查 Agent 是否已把文件写好，两者取更优者。

---

## 1. 启动 Agent 的两种方式

框架里所有 Agent 调用都通过 **`subprocess.Popen`**（webapp）或 **`subprocess.run`**（CLI）执行，
不进入交互式界面。

### Web 工作台（`scripts/webapp.py`）

```bash
python3 scripts/webapp.py --open          # http://127.0.0.1:8000
```

在网页里填论文 → 选「提示词版本(原版/详细)」「Agent(opencode/codex)」→ 点「开始生成解读」。
背后 `api_generate` 收到参数后 `start_job(...)` 起一个**后台线程**跑 `run_generation_job`，
用 `Popen` 启动 Agent 并**逐行**读取 stdout 打日志。

### CLI（`scripts/generate.py`）

```bash
python3 scripts/generate.py --paper "https://arxiv.org/abs/2408.06292" \
    --prompt original --backend opencode --version original
```

参数：

| 参数 | 作用 |
|------|------|
| `--paper` | arXiv 链接 或 本地 PDF 路径 |
| `--prompt` | `original`（原版 7 段）/ `detailed`（详细 15 节） |
| `--backend` | `opencode` / `codex` / `manual` |
| `--id` | 稳定 id（默认从论文推断） |
| `--version` | 版本名，写盘为 `<id>.json`(original) 或 `<id>__<version>.json` |
| `--model` | 指定模型（默认用 Agent 配置） |
| `--manual` | 只生成一个 content 模板，不调用 Agent |

---

## 2. opencode 的调用

### 2.1 命令

```python
# webapp.py / generate.py 中构造的 cmd 一致
cmd = ["opencode", "run", msg, "--format", "json", "--dir", str(ROOT)]
if model:
    cmd += ["--model", model]
```

等价于命令行：

```bash
opencode run "<提示词+论文+目标路径>" --format json --dir /abs/path/paper-framework [--model xxx]
```

各参数：

| 参数 | 说明 |
|------|------|
| `run` | 非交互跑一次，带消息即任务 |
| `--format json` | **关键**：输出 **NDJSON**（每行一个 JSON 事件），供逐行解析日志/正文 |
| `--dir <ROOT>` | 在 paper-framework 目录下运行，让它能看到 `content/`、`prompts/` 等 |
| `--model` | 覆盖默认模型（可选） |

### 2.2 opencode 的事件流（NDJSON）

`--format json` 让 stdout 变成一行一个 JSON 对象，常见事件：

```jsonc
{"type":"step_start","part":{...}}                                  // 开始一步
{"type":"text","part":{"text":"Let me extract figures..."}}         // Agent 说的正文
{"type":"tool_use","part":{"tool":"bash","state":{"input":{"command":"ls"},
        "output":"content\nindex.html\n","status":"completed"}}}    // 调用了工具
{"type":"step_finish","part":{"reason":"stop"}}                     // 一步结束
```

`_opencode_readable()` 把它转成可读日志：

| 事件 | 展示为 |
|------|--------|
| `step_start` | `… 进入下一步` |
| `text` | 原样正文 |
| `tool_use` | `├ 调用工具 bash $ ls  ↳ output尾行（N 行）` |
| `step_finish` | `✓ 完成一步（stop）` |
| `error` | `✗ 出错：...` |

### 2.3 提取正文

```python
def _opencode_assistant_text(raw):
    # 只取 type=="text" 的 part.text 拼接
    return "\n".join(...)
```

这份"正文"喂给 `_extract_json()` 尝试解析出 `content.json`。

---

## 3. codex 的调用

### 3.1 命令（经 `codex_compat.py` 构造）

```python
# codex_compat.codex_cmd([msg]) 返回：
cmd = ["codex", "exec", msg,
       "--sandbox", "workspace-write",
       "--skip-git-repo-check",
       "--json",
       "-c", f"model_catalog_json={catalog}"]      # catalog 是自动生成的兼容副本
```

等价于命令行：

```bash
codex exec "<提示词+论文+目标路径>" \
  --sandbox workspace-write \
  --skip-git-repo-check \
  --json \
  -c "model_catalog_json=/abs/path/.cache/cc-switch-model-catalog.json.fixed.json"
```

各参数：

| 参数 | 说明 |
|------|------|
| `exec` | 非交互执行 |
| `--sandbox workspace-write` | **只写项目目录**，让它能写 `content/*.json`（若用 `read-only` 就写不了盘，只能回传 JSON） |
| `--skip-git-repo-check` | 允许在非 git 目录运行 |
| `--json` | **关键**：输出 **JSONL 事件流** |
| `-c model_catalog_json=...` | 指向**自动补全字段**的模型目录副本 |

### 3.2 为什么需要 `model_catalog_json` 覆盖（codex_compat.py）

`cc-switch` 会向 `~/.codex/config.toml` 写入 `model_catalog_json = "cc-switch-model-catalog.json"`，
但该文件缺 `base_instructions` 等字段，新版 codex 启动即崩：

```
failed to parse model_catalog_json ... missing field `base_instructions`
```

桌面端 codex 不受影响（用另一份配置、不读这个文件）。**修复：** `make_fixed_catalog()` 从原文件读出，
仅补齐缺失字段（`base_instructions`、`supports_parallel_tool_calls` 等），写到 `.cache/`，**不改动原文件**，
再用 `-c` 覆盖传入。

### 3.3 codex 的事件流（JSONL）

`--json` 让 stdout 变成一行一个 JSON 事件：

```jsonc
{"type":"thread.started","thread_id":"..."}                 // 会话开始
{"type":"turn.started"}                                     // 开始一轮
{"type":"item.completed","item":{"type":"reasoning","text":"..."}}    // 思考
{"type":"item.completed","item":{"type":"command_execution",
   "command":"ls","aggregated_output":"...","exit_code":0}} // 执行的命令
{"type":"item.completed","item":{"type":"agent_message","text":"..."}} // 正式消息
{"type":"turn.completed","usage":{"output_tokens":123}}    // 本轮结束 + token
```

`_codex_readable()` 展示：

| 事件 | 展示为 |
|------|--------|
| `thread.started` | `▶ 启动 codex 会话` |
| `turn.started` | `… 开始一轮处理` |
| `reasoning` | `🧠 <思考首行>` |
| `command_execution` | `├ 执行命令 $ cmd  ↳ 输出尾行（N 行）`；失败 `⚠ 命令退出码 N：$ cmd` |
| `agent_message` | 原样正文 |
| `file_write`/`patch` | `✎ 写文件 path` |
| `turn.completed` | `✓ 本轮完成（输出 N tokens）` |

`_codex_assistant_text()` 抽取 `agent_message` + `reasoning` 的正文，用于解析 JSON。

---

## 4. 提示词（prompts / build_message）

### 4.1 build_message：给 Agent 的完整消息

```python
def build_message(prompt, paper, out_id="", version="original"):
    if version == "original":
        target = f"content/{out_id}.json"
        vnote = ""
    else:
        target = f"content/{out_id}__{version}.json"
        vnote = f"\n⚠️ 重要：本次生成的是「{version}」版本，必须把完整 content.json 写到 `{target}`，绝对不要写在 `content/{out_id}.json`（那是原版，不能覆盖）。\n"
    return f"{prompt}\n\n请解读并生成 content.json。论文：{paper}\n" \
           + f"输出目标文件：{target}（写盘到该路径）\n" + vnote + "不要输出其它说明。"
```

即：**任务 = prompt 文件全文 + 论文地址 + 目标文件路径 + 版本警告**。
`prompt` 是 `prompts/original.md` 或 `prompts/detailed.md` 的全文。

### 4.2 两套提示词

**原版 `prompts/original.md`（快速理解，7 段）**：把论文教学化重写，不压缩原文。

| 章节 | 语义块 |
|------|--------|
| 01 问题 | `section` `p` `callout(tip)` |
| 02 翻译 | `section` `p` `concept` `insight` |
| 03 架构/方法 | `section` `sub` `p` `figure` `formula` |
| 04 关键结果 | `section` `table` `insight` |
| 05 评价 | `section` `verdict` `proscons` |
| 06 博导审稿 | `section` `review`(五维 strong/weak/mixed + overall) |
| 一句话总结 | `takeaway` |

**详细版 `prompts/detailed.md`（科研级，15 节 + 证据可追溯）**：在“指导 20 年的博导”视角做科研级拆解，
每个关键判断带 `evidence`（Section/Page/Figure/Table/Equation）。

| 章节 | 语义块 |
|------|--------|
| 01 一句话 | `insight` |
| 02 问题 | `p` `callout(warn)` |
| 03 Existing Work | `p` `list` `callout(tip)` |
| 04 核心思想 | `concept` `insight` |
| 05 方法 | `sub` `p` `concept` `formula` |
| 06 图解 | `figure` + `p` |
| 07 关键公式 | `formula` |
| 08 实验设置 | `p` `list` `table` |
| 09 关键结果 | `table` `insight` |
| 10 消融实验 | `table` `callout(info)` |
| 11 贡献 | `concept` x2 `proscons` |
| 12 局限 | `p` `callout(warn)` |
| 13 博导审稿 | `review`(五维 + overall) |
| 14 对我的启发 | `p` `callout(tip)` |
| 15 阅读原文定位 | `table`(内容/原文位置) |

两套都强调“**交付方式**”：把结果**直接写入任务约定的那个文件**，不要另起文件名、不要覆盖其它版本；
图片是加分项，遇到矢量拆分/反复失败**立即跳过**，先保证写出 `content.json`。

---

## 5. 结果如何落盘与识别

Agent 跑完后 `run_generation_job` 按顺序判断：

1. **目标文件是否已被 Agent 写盘**　`content/<id>.json`(original) 或 `content/<id>__<version>.json`
   且非 stub（不是空 blocks / 占位标题）→ 直接采用。
2. **从输出正文 parse 出 JSON**（`_extract_json`）→ 用它。
3. 都没有 → 存 `content/<id>.raw.txt` 原始输出，状态 error，提示手填。

`version` 决定文件名：`original` → `<id>.json`；其它 → `<id>__<version>.json`。
同一 id 的不同版本文件由 `load_versions(id)` 聚合，最终 `render_paper()` 内嵌所有版本供页内切换。

---

## 6. 直接用 CLI 跑一条示例

```bash
cd paper-framework

# 用 opencode + 原版提示词生成 mamba 的解读
python3 scripts/generate.py \
    --paper "https://arxiv.org/abs/2312.00752" \
    --prompt original --backend opencode --version original

# 渲染成网页（含原版+详细切换）
python3 scripts/render.py mamba
python3 scripts/serve.py            # 或 python3 scripts/webapp.py --open
```

要换 codex：`--backend codex`（会自动处理 `model_catalog_json` 兼容、`workspace-write`、`--json`）。

---

## 7. 常见问题

| 现象 | 原因 |
|------|------|
| codex 直接报 `missing field base_instructions` | `cc-switch` 写的模型目录缺字段；框架已自动生成兼容副本覆盖，若仍现说明 `.cache` 未生成 |
| codex 只能回传 JSON、不写盘 | 曾用 `--sandbox read-only`；现固定 `workspace-write` 以允许写 `content/` |
| 「未能解析 JSON，原始输出已存 .raw.txt」 | Agent 没写盘、也没把 JSON 放进正文（它可能只写了个模板） |
| 生成很慢 | LLM 正在联网/检索论文/提取图片，属 normal；图片提取失败会自动跳过 |
| 论文页没有版本切换按钮 | 该 id 只有一个版本；存在 `<id>__detailed.json` 才会显示「原版/详细」 |

---

## 8. 关键源码索引

| 位置 | 功能 |
|------|------|
| `scripts/generate.py::build_message` | 拼装 Agent 提示词 + 目标路径 + 版本警告 |
| `scripts/generate.py::run_backend` | 启动 opencode/codex，提取正文，检测写盘文件 |
| `scripts/generate.py::_opencode_assistant_text` / `_codex_assistant_text` | 从事件流抽正文 |
| `scripts/webapp.py::run_generation_job` | Web 版后台线程，`Popen` 逐行打日志 |
| `scripts/webapp.py::_opencode_readable` / `_codex_readable` | 事件 → 可读日志 |
| `scripts/codex_compat.py::codex_cmd` / `make_fixed_catalog` | codex 命令构造 + 模型目录兼容 |
| `scripts/render.py::load_versions` / `render_paper` | 聚合多版本并渲染 |
| `prompts/original.md` / `detailed.md` | 两套提示词全文 |
