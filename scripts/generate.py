#!/usr/bin/env python3
"""
generate.py —— 生成论文解读 content.json（opencode / codex / 手动导入 三选一）

用法:
    python3 scripts/generate.py --paper <arxiv链接或PDF> --prompt original --backend opencode
    python3 scripts/generate.py --paper <...> --prompt detailed  --backend codex
    python3 scripts/generate.py --manual --id my-paper-file        # 手动：只生成内容模板

流程:
    论文 → (LLM + 提示词) → content/<id>.json → render.py → papers/<id>/index.html
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import codex_compat  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
CONTENT = ROOT / "content"

BACKENDS = ("opencode", "codex", "manual")


def load_prompt(variant: str) -> str:
    p = PROMPTS / f"{variant}.md"
    if not p.exists():
        print(f"提示词不存在：{p}", file=sys.stderr)
        sys.exit(1)
    return p.read_text(encoding="utf-8")


def build_message(prompt: str, paper: str, out_id: str = "", version: str = "original") -> str:
    if version == "original":
        target = f"content/{out_id}.json" if out_id else ""
        vnote = ""
    else:
        target = f"content/{out_id}__{version}.json" if out_id else ""
        vnote = (f"\n⚠️ 重要：本次生成的是「{version}」版本，必须把完整 content.json 写到 "
                 f"`{target}`，绝对不要写在 `content/{out_id}.json`（那是原版，不能覆盖）。\n")
    return (
        f"{prompt}\n\n"
        f"请解读并生成 content.json。论文：{paper}\n"
        + (f"输出目标文件：{target}（写盘到该路径）\n" if target else "")
        + vnote
        + "不要输出其它说明。"
    )


def guess_id(paper: str) -> str:
    """从 arXiv 或文件名生成一个目录名。"""
    paper = paper.strip()
    import re
    m = re.search(r"arxiv\.org/abs/([0-9.]+)", paper)
    if m:
        return m.group(1)
    m = re.search(r"arxiv\.org/pdf/([0-9.]+)", paper)
    if m:
        return m.group(1)
    name = Path(paper.split("?")[0]).stem
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return name or datetime.now().strftime("%Y%m%d%H%M")


def run_backend(backend: str, prompt: str, paper: str, out_path: Path, model: str | None,
                version: str = "original"):
    msg = build_message(prompt, paper, out_path.stem, version)
    before = {f.name for f in CONTENT.glob("*.json")}
    if backend == "opencode":
        cmd = ["opencode", "run", msg, "--format", "json", "--dir", str(ROOT)]
        if model:
            cmd += ["--model", model]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=None)
        text = _opencode_assistant_text(proc.stdout) or proc.stdout
    elif backend == "codex":
        cmd = codex_compat.codex_cmd([msg])
        if model:
            cmd += ["--model", model]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=None)
        text = _codex_assistant_text(proc.stdout) or proc.stdout
    else:
        raise ValueError(backend)
    if not isinstance(text, str) or not text.strip():
        print("Agent 无有效文本输出", file=sys.stderr)
        return False
    # 1) Agent 可能直接把文件写好了
    agent_wrote = [f.stem for f in CONTENT.glob("*.json")
                   if f.name not in before and f.name != "papers.json"]
    if agent_wrote:
        print(f"✓ Agent 已写入 content/{agent_wrote[0]}.json")
        return True
    retry = _extract_json(text)
    if not retry:
        print("未能从 Agent 输出中解析出 JSON。原始输出：", file=sys.stderr)
        print(text[:3000], file=sys.stderr)
        # 把原始输出留档，便于手动拷贝
        keep = out_path.with_suffix(".raw.txt")
        keep.write_text(text, encoding="utf-8")
        print(f"原始输出已保存 → {keep}", file=sys.stderr)
        return False
    # 规范化：补 datetime / id
    data = retry
    data.setdefault("id", out_path.stem)
    data.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ content.json → {out_path}")
    return True


def _opencode_assistant_text(raw: str) -> str:
    """opencode --format json 输出 NDJSON 事件行，抽取其中 assistant 的 text part。"""
    if not raw or not isinstance(raw, str):
        return ""
    parts = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") != "text":
            continue
        part = ev.get("part") or {}
        if isinstance(part, dict) and part.get("text"):
            parts.append(part["text"])
    return "\n".join(parts)


def _codex_assistant_text(raw: str) -> str:
    """codex exec --json 输出 JSONL 事件行，抽取 agent_message 与 reasoning 正文。"""
    if not raw or not isinstance(raw, str):
        return ""
    parts = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") != "item.completed":
            continue
        item = ev.get("item") or {}
        if not isinstance(item, dict):
            continue
        it = item.get("type")
        if it == "agent_message":
            parts.append(item.get("text", ""))
        elif it == "reasoning":
            parts.append(item.get("text", ""))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _extract_json(text: str) -> str | None:
    import re
    if not isinstance(text, str):
        return None
    # 去掉 ```json ``` 包裹
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # 找第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass
    return None


def make_manual_template(out_path: Path):
    """手动导入：生成一个带注释的模板，用户填空后调用 render.py。"""
    tmpl = {
        "id": out_path.stem,
        "title": "论文标题",
        "subtitle": "一句话副标语（可选）",
        "authors": "作者列表",
        "affiliation": "机构（可选）",
        "source": "arXiv / 期刊 / 会议",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "tags": ["tag1", "tag2"],
        "summary": "一句话简介",
        "blocks": [
            {"type": "section", "num": "01", "title": "问题"},
            {"type": "p", "text": "论文解决什么问题、为什么难、以前方法为何不够。"},
            {"type": "section", "num": "02", "title": "翻译"},
            {"type": "concept", "title": "核心概念", "body": "什么是它", "why": "为什么重要"},
            {"type": "section", "num": "03", "title": "架构 / 方法"},
            {"type": "formula", "title": "关键公式", "tex": "$$E=mc^2$$", "note": "每个符号含义"},
            {"type": "section", "num": "04", "title": "关键结果"},
            {"type": "table", "title": "Benchmark",
             "headers": ["Model", "A"], "rows": [["Baseline", 10], ["Ours", 20]],
             "highlights": [[1, 1]], "caption": "提升 10 个点。"},
            {"type": "section", "num": "05", "title": "评价"},
            {"type": "verdict", "text": "综合判断"},
            {"type": "proscons", "pros": ["优点1"], "cons": ["局限1"]},
            {"type": "section", "num": "06", "title": "博导审稿"},
            {"type": "review",
             "summary": "20 年博导视角",
             "dimensions": [
                 {"name": "选题眼光", "grade": "strong", "note": "……"},
                 {"name": "方法成熟度", "grade": "mixed", "note": "……"},
                 {"name": "实验诚意", "grade": "weak", "note": "……"},
                 {"name": "写作功力", "grade": "strong", "note": "……"},
                 {"name": "影响力预判", "grade": "mixed", "note": "……"}],
             "overall": "Strong Accept", "overallSub": "推荐精读。"},
            {"type": "takeaway", "text": "一句话总结。"}
        ],
    }
    out_path.write_text(json.dumps(tmpl, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 手动模板 → {out_path}\n  请编辑该 JSON 后用：python3 scripts/render.py {out_path.stem}")


def main():
    ap = argparse.ArgumentParser(description="生成论文解读 content.json")
    ap.add_argument("--paper", help="arXiv 链接或本地 PDF 路径")
    ap.add_argument("--prompt", choices=("original", "detailed"), default="original",
                    help="提示词版本：原版 / 详细")
    ap.add_argument("--backend", choices=BACKENDS, default="opencode",
                    help="用哪个 Agent 生成")
    ap.add_argument("--id", help="强制指定目录名（默认从论文推断）")
    ap.add_argument("--model", help="模型（如 openai/gpt-4o，默认用 Agent 配置）")
    ap.add_argument("--version", default="original",
                    help="版本名：original（默认）/ detailed 等，写盘为 <id>__<version>.json")
    ap.add_argument("--manual", action="store_true", help="手动导入：仅生成 content 模板")
    args = ap.parse_args()

    # 校验 agent 可用
    if not args.manual:
        if not args.paper:
            print("需要 --paper（arxiv 链接或 PDF 路径）", file=sys.stderr)
            return 1
        if args.backend != "manual" and shutil.which(args.backend) is None:
            print(f"未找到可执行文件：{args.backend}", file=sys.stderr)
            return 1

    pid = args.id or guess_id(args.paper or "paper")

    if args.manual:
        out_path = CONTENT / (f"{pid}.json" if args.version == "original" else f"{pid}__{args.version}.json")
        make_manual_template(out_path)
        return 0

    out_path = CONTENT / (f"{pid}.json" if args.version == "original" else f"{pid}__{args.version}.json")
    prompt = load_prompt(args.prompt)
    ok = run_backend(args.backend, prompt, args.paper, out_path, args.model, version=args.version)
    if not ok:
        print("生成失败，脚本已尽力。", file=sys.stderr)
        return 1
    print(f"现在渲染：python3 scripts/render.py {pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
