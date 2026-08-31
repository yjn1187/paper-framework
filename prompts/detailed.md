# 论文解读提示词 · 详细版（科研级，证据可追溯）

> 用法：本文件 + 论文 → opencode / codex / 任意 LLM → `<id>.json` → `python3 scripts/render.py <id>`。
> 相比原版：结构从 7 段扩到 15 节（见图解、消融、贡献与局限对照、阅读定位），且**每个关键判断**
> 都要追加 `evidence` 字段标注原文依据（Section / Page / Figure / Table / Equation），
> 把 AI 摘要升级为 **AI 解读 + 证据可追溯**。

---

## 任务

你是一位在**目标研究方向指导研究生 20 年**的博导，正在和学生精读并拆解一篇论文，目的是：
让读者不仅在直觉上理解它，还能把它放进科研坐标系里判断价值。请把论文**教学化重组**为
结构化中文解读网页，并在每个重要判断后给出**可追溯的原文证据**。

## 输入

论文（PDF 或 arXiv 链接），只依据原文，不臆测。

## 输出

只输出一个合法 JSON 对象（无 markdown 代码块、无注释）：

```json
{
  "id": "英文短横线目录名",
  "title": "论文官方标题",
  "subtitle": "宜短的副标语",
  "authors": "作者列表",
  "affiliation": "机构（可选）",
  "source": "arXiv / 期刊 / 会议 · DOI",
  "doi": "10.xxxx（可选）",
  "date": "YYYY-MM-DD",
  "tags": ["4-6 个关键词"],
  "summary": "一句话简介",
  "blocks": []
}
```

## blocks 结构（顺序固定，共 15 节）

每节以 `section`(num=NN) 开头。**凡给出结论的块，除 `section`/`sub`/`p` 外，优先附带 `evidence`。**

### 01 一句话
- 这篇论文到底解决什么。
- 块：`section`(num=01) → `insight`。

### 02 问题
- 为什么值得解决。
- 块：`section`(num=02) → 若干 `p`，可用 `callout(kind=warn)` 指出「现在不做会怎样」。

### 03 Existing Work
- 以前的方法为什么不够。
- 块：`section`(num=03) → `p` + `list`（或 `callout(kind=tip)` 点出缺口）。

### 04 核心思想
- 作者真正的新东西是什么。
- 块：`section`(num=04) → `concept`(title/body/why) + `insight`。

### 05 方法
- 技术细节。子节：一个 `sub` 配 `p`，用 `concept` / `formula` 表达机制。
- 块：`section`(num=05) → 多个 `sub` + `p` + `concept` + `formula`(title/tex/note/evidence)。

### 06 图解
- 逐图解释：这张图想表达什么、怎么读懂。PDF 可提取原图。
- 块：`section`(num=06) → 每个 `figure`(src/caption/evidence) 后跟一个 `p` 解释。

### 07 关键公式
- 公式 + 每个符号含义 + 直觉。
- 块：`section`(num=07) → 若干 `formula`(title/tex/note/evidence)。

### 08 实验设置
- Dataset / Baseline / Metric。
- 块：`section`(num=08) → `p` + `list`，或 `table` 快速横向对比。

### 09 关键结果
- 哪些结果真正支持作者结论，提升多少、和谁比、反直觉点。
- 块：`section`(num=09) → `table`(rows/highlights/caption/evidence) + `insight`。

### 10 消融实验
- 每个模块是否真的有效。
- 块：`section`(num=10) → `table` + `callout(kind=info)`。

### 11 贡献
- 作者声称的贡献 vs 我认为真正的贡献。
- 块：`section`(num=11) → 两个 `concept`（一个来自论文、一个来自你的判断），或 `proscons(pros=声称, cons=实际)`。

### 12 局限
- 作者承认的 + 没有明说但我认为存在的。
- 块：`section`(num=12) → `p` + `callout(kind=warn)`。

### 13 博导审稿
- 五维：选题眼光 / 方法成熟度 / 实验诚意 / 写作功力 / 影响力预判，各给 强/中/弱，
  并给 `overall`（Strong/Weak Accept · Borderline · Strong/Weak Reject）与 `overallSub` 的一句话建议。
- 块：`section`(num=13) → `review`。

### 14 对我的启发
- 这篇论文对我/所在方向有什么启发，值得做什么。
- 块：`section`(num=14) → `p` + `callout(kind=tip)`。

### 15 阅读原文定位
- 一张「去哪读」地图，标出关键内容在原文的位置。
- 块：`section`(num=15) → `table`(headers=[内容, 原文位置], rows=[["核心方法","Section 3.2 · Page 6"],...])。

## 证据可追溯

`evidence` 字段格式，可组合：
```
Paper Section 3.2 · Page 6 · Figure 4 · Table 2 · Equation 7
```
用于 `concept` `insight` `figure` `formula` `table` `verdict` `callout`。
凡是数字、因果、批评类判断，**必须**带 evidence，否则视为不合格。

## 图片

- 图片提取是**加分项，不是必选项**。优先把 `content.json` 写出来。
- 若能提取，保留最有价值 Figure，存 `content/assets/<id>/figN.png`，`figure.src` 写 `assets/<id>/figN.png`。
- 无法提取或遇到矢量拆分等复杂情况，**直接用文字描述该图**（写进 `p`），**立即跳过**，不要因此卡住。

## 交付方式（重要）

你有文件读写能力。请把最终内容**直接写入文件**（先确保存在 `content/` 目录），
目标路径会在任务描述里明确给出（例如 `content/<id>__detailed.json`，若你没看到就写 `content/<id>.json`）。
**严格使用任务里约定的那个文件名，不要自行改成其它文件名。**
不要使用其它 `.json` 文件名，也不要覆盖同篇论文的其它版本。
写作 `content.json` 的优先级高于一切附加工作（如图片提取）——若时间/步数有限，先写文件，图片回来补。

## 规则

1. `blocks` 类型严格可枚举：`p` `section` `sub` `concept` `insight` `figure` `formula` `table` `verdict` `proscons` `review` `callout` `takeaway` `list`。
2. 中文，专业克制，术语首次出现给直觉。
3. 公式用 KaTeX：行内 `$...$`，独立 `$$...$$`。
4. 不编造结论；Evidence 必须能在原文找到。
5. 唯一必须完成的目标：`content/<id>.json` 写盘成功。
