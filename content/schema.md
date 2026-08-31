# content.json —— 论文解读内容 Schema

`content.json` 是本框架的**唯一中间产物**。无论用 opencode、codex 生成，还是手动编写，
都输出同一个结构。`render.py` 把它打包成**自包含的单文件 `index.html`**（双击即可阅读）。

## 思路

```
论文 PDF / arXiv
      │  原版 / 详细 提示词
      ▼
   LLM (opencode / codex / 手动)
      ▼
   content JSON  →  render.py  →  index.html
```

AI 只负责**判断信息类型**并填进对应字段；**视觉由这套固定的语义组件决定**。

## 顶层字段

```jsonc
{
  "id": "stable-paper-id",          // 同一篇论文所有版本共用的稳定 id（如 "mamba"）
  "version": "original",            // 版本：original(原版) / detailed(详细) / 其它自定义
  "title": "官方标题",
  "subtitle": "一句话副标语",        // 可选
  "authors": "作者列表",
  "affiliation": "机构（可选）",
  "source": "https://arxiv.org/abs/xxxx",   // 原始来源链接（打开论文网页）
  "source_pdf": "uploads/xxx.pdf",          // 本地原始 PDF 相对路径（可选，若上传过）
  "doi": "10.xxxx/xxxx (可选)",
  "date": "2026-08-31",
  "tags": ["AI Scientist", "Agent"],
  "summary": "元数据下方展示的一句话简介（可选）",
  "theme": "ink",                   // 可选：主题 "ink"(默认) / "simona"
  "blocks": [ ... ]                 // 正文语义块数组
}
```

## 版本管理（原版 / 详细）

同一篇论文用一个**稳定 `id`** 下的多个 JSON 文件表示不同解读版本：

```
content/
├── <id>.json               # 默认版本（通常 = original），无 __ 后缀
├── <id>__detailed.json    # 详细版
├── <id>__meta.json        # 共享元信息（title/authors/source/source_pdf/tags/icon/doi/date）
├── papers.json            # 论文清单（每篇出现一次，指向它的各版本）
└── assets/<id>/<version>/ # 各版本图片（原版/详细分开，避免覆盖）
```

- 每个版本 JSON 都自包含（各有自己的 `blocks` / `summary` / `theme`），
  但 `title/authors/source/source_pdf` 等**元信息可用 `<id>__meta.json` 共享**；版本文件可省略重复字段。
- 渲染时 `render.py <id>` 会自动合并所有 `content/<id>*.json` 版本，页内右上角「原版／详细」一键切换。
- **id 冲突避免**：改版本不要新建 id。若文件被命名为 `<id>22`、`<id>__副本` 等，属于多余文件，应删除或归并到 `<id>__<version>.json`。

## 主题（theme）

`ink` —— paper-framework 默认（衬线、砖红、760px 正文）；
`simona` —— 复刻 https://blog.simona.plus/ 原 paper-to-html 主题（无衬线、紫、绿色博导审稿卡片、黄色 verdict）。
优先级：命令行 `--theme` > `content.json` 的 `theme` 字段 > 默认 `ink`。

> 渲染产物会内嵌全部主题，页面右上角有浮动切换器，可在 `ink`/`simona` 间即时切换（无需重新渲染）。

## blocks —— 语义块类型

严格按顺序排列；各组件名称与 CSS 类别一致。

### `p` 段落
```jsonc
{ "type": "p", "text": "Markdown 段。支持 **加粗**、*斜体*、`代码`、$inline 公式$。" }
```

### `section` 章节标题
```jsonc
{ "type": "section", "num": "01", "title": "问题" }
```

### `sub` 小节标题
```jsonc
{ "type": "sub", "title": "核心思想" }
```

### `concept` 核心概念
```jsonc
{ "type": "concept", "title": "Agentic Tree Search",
  "body": "什么是它……",
  "why": "为什么重要……" }
```

### `insight` 核心洞见
```jsonc
{ "type": "insight", "text": "真正重要的不是……而是……" }
```

### `figure` 论文原图
```jsonc
{ "type": "figure", "src": "assets/<id>/fig1.png",
  "caption": "Figure 1：论文整体方法。",
  "evidence": "Paper Figure 1, Page 3" }
```

### `formula` 关键公式
```jsonc
{ "type": "formula", "title": "损失函数",
  "tex": "$$L(\\theta) = \\sum_i \\ell_i$$",
  "note": "每个符号含义……",
  "evidence": "Equation 7, Page 5" }
```

### `architecture` 等宽架构块（simona 主题常用）
```jsonc
{ "type": "architecture",
  "text": "dμ₀/dt = B        (成核)\ndμ₁/dt = G·μ₀  (一阶矩)",
  "evidence": "Page 3" }
```
等宽字体、`white-space:pre` 保留换行，适合多行方程/流程。`ink` 主题同样支持。

### `table` 关键结果表
```jsonc
{ "type": "table", "title": "Benchmark 结果",
  "headers": ["Model", "Dataset A", "Dataset B"],
  "rows": [ ["Baseline", 12.1, 8.4], ["Ours", 18.3, 14.9] ],
  "highlights": [ [1, 1], [1, 2] ],     // [row, col] 0-based，高亮（可选）
  "caption": "提升约 6.2 个点。",
  "evidence": "Table 2, Page 7" }
```

### `verdict` 判断
```jsonc
{ "type": "verdict", "text": "这篇工作工程完成度很高，但核心创新在 Agent Workflow……" }
```

### `proscons` 评价
```jsonc
{ "type": "proscons", "pros": ["…", "…"], "cons": ["…", "…"] }
```

### `review` 博导审稿
```jsonc
{ "type": "review", "summary": "在这方向指导 20 年的博导视角：……",
  "dimensions": [
    { "name": "选题眼光", "grade": "strong",  "note": "（strong/weak/mixed）……" },
    { "name": "方法成熟度", "grade": "mixed", "note": "……" },
    { "name": "实验诚意",   "grade": "weak",   "note": "……" },
    { "name": "写作功力",   "grade": "strong", "note": "……" },
    { "name": "影响力预判", "grade": "mixed",  "note": "三年后是否还有人引用……" }
  ],
  "overall": "Strong Accept",
  "overallSub": "推荐精读，值得深入跟进。" }
```

### `callout` 通用提示框
```jsonc
{ "type": "callout", "kind": "info|warn|tip",
  "title": "可选标题", "text": "内容……" }
```

### `takeaway` 一句话总结（置于文末）
```jsonc
{ "type": "takeaway", "text": "把这篇论文总结成一句话。" }
```

### `list` 列表（仅正文用）
```jsonc
{ "type": "list", "ordered": false, "items": ["…", "…"] }
```

## 图片约定

1. 论文重要 Figure 提取到 `content/assets/<id>/` 目录。
2. 建议文件名 `fig1.png`、`fig2.png`……并在 `figure.src` 写 `assets/<id>/fig1.png`。
3. 无图时可省略 `figure` 组件。

## 证据可追溯（推荐，详细版必选）

任何关键判断后，可附加 `evidence` 字段，格式：

```
Paper Section 3.2 · Page 6 · Figure 4 · Table 2 · Equation 7
```

渲染成灰字小注，让解读从 AI 摘要升级为 **AI 解读 + 证据可追溯**。
