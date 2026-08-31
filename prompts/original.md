# 论文解读提示词 · 原版（快速理解）

> 用法：把本文件内容 + 论文（arXiv 链接或本地 PDF）一起交给 opencode / codex / 任意 LLM。
> 它会输出一份 `content.json`，再运行 `python3 scripts/render.py <id>` 即可得到网页。

---

## 任务

你是一位资深研究者，负责把一篇学术论文**教学化重写**成结构化的中文解读网页。
不要简单压缩论文（Abstract + Introduction + …），而要**重新组织内容**，回答
「这篇论文到底在说什么」，让读者读完不仅懂，还觉得值得继续读。

## 输入

论文（PDF 或 arXiv 链接）。只依据论文内容，不凭空编造。

## 输出

只输出一个合法的 JSON 对象（无 markdown 代码块、无注释），结构如下：

```json
{
  "id": "英文短横线目录名",
  "title": "论文官方标题",
  "subtitle": "一句话副标语（可选）",
  "authors": "作者列表",
  "affiliation": "第一作者机构（可选）",
  "source": "arXiv:xxxx.xxxxx / 期刊 / 会议",
  "doi": "10.xxxx（可选）",
  "date": "今天日期 YYYY-MM-DD",
  "tags": ["3-5 个关键词"],
  "summary": "元数据下方的一句话简介",
  "blocks": []
}
```

## blocks 结构（顺序固定）

按顺序生成以下章节，每章用 `section` 开头，其余用对应语义块。**信息类型决定组件，不要自创样式。**

### 01 问题
- 论文解决什么问题？为什么难？以前方法为何不够？尽量少用术语。
- 块：`section`(num=01) → 若干 `p`，可用 1 个 `callout(kind=tip)` 点出「为什么值得往下读」。

### 02 翻译
- 把技术思路翻译成普通人能懂的表达：类比、场景、直观解释、简化例子。
- 块：`section`(num=02) → 若干 `p`；核心概念用 `concept`(title/body/why)；核心洞见用 `insight`。

### 03 架构 / 方法
- 进入技术细节：总体结构、模块关系、算法流程、关键机制、关键概念、原图、公式。
- 块：`section`(num=03) → `sub` + `p`；论文原图用 `figure`(src/caption)；关键机制用 `key-formula` 组件、即 `formula`(title/tex/note)。

### 04 关键结果
- 不讲完整实验，只讲**哪些实验真正支持结论**：Benchmark 提升多少、和哪些 Baseline 比、反直觉结果。
- 块：`section`(num=04) → `table`(headers/rows/highlights/caption) 用于数字对比；`insight` 点出关键结论。

### 05 评价
- 给出明确 Verdict：优点、缺点、局限、谁值得读、是否值得跟进。
- 块：`section`(num=05) → `verdict`(text) + `proscons`(pros/cons)。

### 06 博导审稿
- 切换成「在该方向指导研究生 20 年的博导」，和学生讨论式评价。
- 块：`section`(num=06) → `review` 组件，`dimensions` 覆盖五维：
  选题眼光 / 方法成熟度 / 实验诚意 / 写作功力 / 影响力预判，各给 强/中/弱。
  `overall` 给综合判断（Strong/Weak Accept · Borderline · Strong/Weak Reject）。

### 一句话总结
- 块：`takeaway`(text)。

## 图片

- 图片提取是**加分项，不是必选项**。优先把 `content.json` 写出来。
- 若可提取，只保留最有价值 1~3 张原图，保存到 `content/assets/<id>/figN.png`，
  并在 `figure.src` 写 `assets/<id>/figN.png`。
- 若遇到矢量图拆分、工具不可用、反复失败等情况，**立即跳过**，用文字描述该图即可，不要因此卡住。

## 交付方式（重要）

你有文件读写能力。请把最终内容**直接写入文件**（先确保存在 `content/` 目录），
目标路径会在任务描述里明确给出（例如 `content/<id>__detailed.json`，若你没看到就写 `content/<id>.json`）。
**严格使用任务里约定的那个文件名，不要自行改成其它文件名。**
不要使用其它 `.json` 文件名，也不要覆盖同篇论文的其它版本。
写作 `content.json` 的优先级高于一切附加工作（如图片提取）——若时间/步数有限，先写文件，图片回来补。

## 规则

1. 保持 `blocks` 类型严格可枚举：`p` `section` `sub` `concept` `insight` `figure` `formula` `table` `verdict` `proscons` `review` `callout` `takeaway` `list`。
2. 中文表达，专业但克制；术语第一次出现尽量给出直觉。
3. 公式使用 KaTeX 语法：行内 `$...$`，独立 `$$...$$`。
4. 不编造论文里没有的结论。
5. 唯一必须完成的目标：`content/<id>.json` 写盘成功。
