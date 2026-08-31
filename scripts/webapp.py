#!/usr/bin/env python3
"""
webapp.py —— 浏览器版论文解读工作台

启动:
    python3 scripts/webapp.py [--port 8000] [--open]

功能（全部在浏览器操作，无需终端命令）:
    - 输入 arXiv 链接 / 上传 PDF → 选择提示词(原版/详细) + 主题(ink/simona) → 生成
    - 实时日志流（正在生成时轮询）
    - 内嵌 JSON 编辑器：生成后可直接改内容，改完即渲染
    - 论文库列表 + 单篇预览
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, send_file

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate as GEN  # noqa: E402
import render as REND  # noqa: E402
import codex_compat  # noqa: E402
import serve as SVR  # noqa: E402

CONTENT = ROOT / "content"
PAPERS = ROOT / "papers"
UPLOADS = ROOT / "content" / "uploads"
WEB = ROOT / "web"

UPLOADS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(WEB), static_url_path="")

JOBS: dict[str, dict] = {}
TASKS_ORDER: list[str] = []

THEMES = ("ink", "simona")


# ---------- 生成任务（后台线程） ----------

def _job_log(job, msg):
    job["log"].append(f"{datetime.now().strftime('%H:%M:%S')} {msg}")
    job["updated"] = time.time()


def run_generation_job(job: dict, paper: str, backend: str, prompt_variant: str,
                       pid: str, model: str | None, attach_files: list[str], version: str = "original"):
    # 记录启动前已有的 content/*.json，便于检测 agent 自己写入的文件
    try:
        _job_log(job, f"开始生成：{prompt_variant} 提示词，backend={backend}")
        prompt = GEN.load_prompt(prompt_variant)
        msg = GEN.build_message(prompt, paper, pid, version)

        if backend == "opencode":
            cmd = ["opencode", "run", msg, "--format", "json", "--dir", str(ROOT)]
            for f in attach_files:
                cmd += ["--file", f]
            if model:
                cmd += ["--model", model]
        elif backend == "codex":
            cmd = codex_compat.codex_cmd([msg])
            if model:
                cmd += ["--model", model]
        else:
            _job_log(job, "未知 backend，取消")
            job["status"] = "error"
            return

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        text = ""
        for line in proc.stdout:
            text += line
            line = line.rstrip("\n")
            short = ""
            if backend == "opencode":
                short = _opencode_readable(line)
            elif backend == "codex":
                short = _codex_readable(line)
            else:
                short = line.strip()
            if not short:
                continue
            # 日志展示得更完整：长内容给 <pre> 折叠控件标记，但仍记录全文到 raw
            if len(short) > 1000:
                short = short[:1000] + "…"
            _job_log(job, short)
        proc.wait()
        job["full_log"] = text.strip()[-20000:]
        if proc.returncode != 0:
            _job_log(job, f"⚠ 进程退出码 {proc.returncode}（见上方输出，可能是 Agent 配置/工具问题）")
            job["raw"] = text
            keep = CONTENT / f"{pid}.raw.txt"
            keep.write_text(text, encoding="utf-8")
            _job_log(job, f"原始输出已存 {keep.name}，可据此排查。")

        body = _assistant_text(backend, text)
        data = GEN._extract_json(body)
        if not data:
            # 回退：从全文抽
            data = GEN._extract_json(text)

        # 本次任务的目标文件（版本化）
        target = CONTENT / (f"{pid}.json" if version == "original" else f"{pid}__{version}.json")

        # 优先：Agent 已把目标文件写盘且非模板
        best = None
        if not data:
            if target.exists():
                try:
                    cand = json.loads(target.read_text(encoding="utf-8"))
                    if not _is_stub(cand):
                        best = cand
                except Exception:
                    best = None

        if best is not None:
            # 读盘得到的，改一下版本标记即可
            best.setdefault("id", pid)
            best["version"] = version
            best.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
            target.write_text(json.dumps(best, ensure_ascii=False, indent=2), encoding="utf-8")
            _job_log(job, f"✓ 解读 (版本 {version}) 已写入 {target.name}")
            job["pid"] = pid
            job["version"] = version
        elif data:
            obj = json.loads(data)
            obj.setdefault("id", pid)
            obj.setdefault("version", version)
            obj.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
            target.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            _job_log(job, f"✓ 解读 (版本 {version}) 已写入 {target}")
            job["pid"] = pid
            job["version"] = version
        else:
            keep = CONTENT / f"{pid}.raw.txt"
            keep.write_text(text, encoding="utf-8")
            _job_log(job, f"未能解析 JSON，原始输出已存 {keep.name}")
            _job_log(job, "可到「编辑器」手填内容，或点击「原始输出」查看。")
            job["status"] = "error"
            job["raw"] = text[:4000]
            return

        # 若使用了标记，把 id/theme 规范化后回写（可选）
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001
        _job_log(job, f"生成异常：{e}")
        job["status"] = "error"


def _is_stub(obj) -> bool:
    """判断内容是否为占位模板（空 blocks 或仍是示例占位标题）。"""
    if not isinstance(obj, dict):
        return True
    blocks = obj.get("blocks")
    if not isinstance(blocks, list):
        return True
    if not blocks:
        return True
    title = obj.get("title", "")
    placeholders = ("论文官方标题", "论文标题", "Untitled", "TITLE")
    if title in placeholders:
        return True
    return False


def _opencode_readable(line: str) -> str:
    """把 opencode 的 NDJSON 事件行转成简短可读日志，非事件返回空。"""
    line = line.strip()
    if not line.startswith("{"):
        return ""
    try:
        ev = json.loads(line)
    except Exception:
        return ""
    t = ev.get("type", "")
    part = ev.get("part") or {}
    if not isinstance(part, dict):
        return ""
    if t == "text":
        return part.get("text", "").strip() or ""
    if t == "step_start":
        return "… 进入下一步"
    if t == "step_finish":
        reason = part.get("reason", "")
        return f"✓ 完成一步（{reason}）" if reason else "✓ 完成一步"
    if t == "error":
        return "✗ 出错：" + str(part.get("message", part))[:200]
    if t in ("tool_use", "tool"):
        name = part.get("tool", "tool")
        state = part.get("state") or {}
        if isinstance(state, dict):
            inp = state.get("input") or {}
            cmd = inp.get("command") if isinstance(inp, dict) else None
            fpath = inp.get("file_path") if isinstance(inp, dict) else None
            out = state.get("output") if state.get("status") == "completed" else None
        else:
            cmd = fpath = out = None
        desc = ""
        if isinstance(cmd, str) and cmd:
            desc = f"  $ {cmd}"
        elif isinstance(fpath, str) and fpath:
            desc = f"  {fpath}"
        if isinstance(out, str) and out.strip():
            tail = out.strip().splitlines()[-1] if out.strip().splitlines() else ""
            if tail:
                more = len(out.strip().splitlines())
                desc += f"  ↳ {tail[:120]}" + (f"（{more} 行）" if more > 1 else "")
        return f"├ 调用工具 {name}{desc}" if desc else f"├ 调用工具 {name}"
    return ""


def _codex_readable(line: str) -> str:
    """把 codex exec --json 的输出事件行转成简短可读日志，非事件返回空。"""
    line = line.strip()
    if not line.startswith("{"):
        return ""
    try:
        ev = json.loads(line)
    except Exception:
        return ""
    t = ev.get("type", "")
    item = ev.get("item") or {}
    if not isinstance(item, dict):
        item = {}
    if t == "thread.started":
        return "▶ 启动 codex 会话"
    if t == "turn.started":
        return "… 开始一轮处理"
    if t == "turn.completed":
        usage = ev.get("usage") or {}
        out_tk = usage.get("output_tokens") if isinstance(usage, dict) else None
        return f"✓ 本轮完成" + (f"（输出 {out_tk} tokens）" if out_tk else "")
    if t == "item.completed":
        it = item.get("type")
        if it == "agent_message":
            return (item.get("text", "").strip() or "") or ""
        if it == "reasoning":
            txt = (item.get("text", "") or "").strip()
            if not txt:
                return ""
            # 只取首行作进度提示
            first = txt.splitlines()[0] if txt.splitlines() else txt
            return f"🧠 {first[:200]}"
        if it == "command_execution":
            cmd = item.get("command") or ""
            out = item.get("aggregated_output") or ""
            status = item.get("status", "")
            exit_code = item.get("exit_code")
            desc = ""
            if isinstance(cmd, str) and cmd:
                desc = f"$ {cmd}"
            if isinstance(out, str) and out.strip():
                tail = out.strip().splitlines()[-1] if out.strip().splitlines() else ""
                if tail:
                    more = len(out.strip().splitlines())
                    desc += f"  ↳ {tail[:120]}" + (f"（{more} 行）" if more > 1 else "")
            if status in ("failed", "error") or exit_code not in (0, None):
                return f"⚠ 命令退出码 {exit_code}：{desc}"
            return f"├ 执行命令{('  '+desc) if desc else ''}"
        if it == "file_write" or it == "patch":
            path = item.get("path") or item.get("file_path") or ""
            return f"✎ 写文件 {path}"
        return ""
    if t == "error":
        return "✗ 出错：" + str(ev.get("message") or ev)[:200]
    return ""


def _codex_assistant_text(text: str) -> str:
    """抽取 codex --json 里 agent_message 与 reasoning 的正文，用于 JSON 解析。"""
    if not isinstance(text, str) or not text:
        return ""
    parts = []
    for line in text.splitlines():
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


def _assistant_text(backend: str, text: str) -> str:
    if backend == "opencode":
        return GEN._opencode_assistant_text(text) or text
    if backend == "codex":
        return _codex_assistant_text(text) or text
    return text

def start_job(paper: str, backend: str, prompt_variant: str, pid: str,
              model: str | None, attach_files: list[str], version: str = "original") -> str:
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "status": "running", "log": [], "pid": None, "version": version,
           "prompt": prompt_variant, "started": time.time(), "updated": time.time()}
    JOBS[jid] = job
    TASKS_ORDER.append(jid)
    t = threading.Thread(target=run_generation_job,
                         args=(job, paper, backend, prompt_variant, pid, model, attach_files, version),
                         daemon=True)
    t.start()
    return jid


# ---------- 路由 ----------

@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/library")
@app.get("/library/")
def library():
    """静态论文库首页（由 webapp 直接提供，无需单独端口）。"""
    papers = SVR.build_library()   # 每次访问刷新索引
    html = SVR.render_index_html(papers)
    return html


@app.post("/api/generate")
def api_generate():
    payload = request.get_json(silent=True) or {}
    paper = (payload.get("paper") or "").strip()
    backend = (payload.get("backend") or "opencode").strip().lower()
    prompt_variant = (payload.get("prompt") or "original").strip().lower()
    version = (payload.get("version") or prompt_variant).strip().lower() or "original"
    model = payload.get("model") or None
    pid = (payload.get("id") or "").strip().lower() or None

    if backend not in ("opencode", "codex"):
        return jsonify({"error": f"unsupported backend: {backend}"}), 400
    if not paper:
        return jsonify({"error": "请填写 arXiv 链接或本地 PDF 路径"}), 400
    if shutil.which(backend) is None:
        return jsonify({"error": f"未找到可执行文件：{backend}"}), 400

    pid = pid or GEN.guess_id(paper)
    # 版本文件：<pid>.json (original 默认) 或 <pid>__<version>.json
    version_file = CONTENT / (f"{pid}.json" if version == "original" else f"{pid}__{version}.json")
    # 若该版本已存在，防覆盖；除非 force
    if version_file.exists() and not payload.get("force"):
        return jsonify({"error": f"已存在 {pid} 的「{version}」版本，请换 version 或先删除"}), 409

    jid = start_job(paper, backend, prompt_variant, pid, model, [], version=version)
    return jsonify({"jid": jid, "pid": pid, "version": version})


@app.get("/api/jobs/<jid>")
def api_job(jid):
    job = JOBS.get(jid)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify({
        "id": jid, "status": job["status"], "pid": job["pid"], "version": job.get("version"),
        "log": job["log"], "raw": job.get("raw"), "stub": job.get("stub", False),
        "full": job.get("full_log", ""),
    })


@app.get("/api/backends")
def api_backends():
    ok_codex, note = codex_compat.codex_available()
    return jsonify({
        "opencode": {"available": True},
        "codex": {"available": ok_codex, "note": note},
    })


@app.get("/api/papers")
def api_papers():
    """以稳定 id 为粒度返回论文清单，每个 id 聚合其各版本。"""
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for f in sorted(CONTENT.glob("*.json")):
        if f.name == "papers.json" or "__meta" in f.name:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        pid = data.get("id") or f.stem.split("__", 1)[0]
        version = data.get("version") or (f.stem.split("__", 1)[1] if "__" in f.stem else "original")
        src_pdf = data.get("source_pdf", "")
        src_url = data.get("source", "")
        if not src_url.startswith("http"):
            src_url = ""
        if pid not in grouped:
            grouped[pid] = {"id": pid, "title": data.get("title", pid),
                            "meta": data.get("subtitle", ""), "tags": data.get("tags", []),
                            "date": data.get("date", ""), "versions": [],
                            "source": src_url, "source_pdf": src_pdf}
            order.append(pid)
        g = grouped[pid]
        g["versions"].append(version)
        if not g["title"] or g["title"] == pid:
            g["title"] = data.get("title", pid)
    items = []
    for pid in order:
        g = grouped[pid]
        g["exists"] = (PAPERS / pid / "index.html").exists()
        items.append(g)
    return jsonify(items)


@app.get("/api/papers/<pid>")
def api_paper(pid):
    f = CONTENT / f"{pid}.json"
    if not f.exists():
        return jsonify({"error": "not found"}), 404
    return jsonify(json.loads(f.read_text(encoding="utf-8")))


@app.put("/api/papers/<pid>")
def api_save_paper(pid):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "content must be a JSON object"}), 400
    if not isinstance(payload.get("title"), str) or not isinstance(payload.get("blocks"), list):
        return jsonify({"error": "content 缺少 title(字符串) 或 blocks(数组)"}), 400
    payload.setdefault("id", pid)
    f = CONTENT / f"{pid}.json"
    f.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


@app.delete("/api/papers/<pid>")
def api_delete_paper(pid):
    removed = []
    # 删除该 id 的所有版本与元信息
    for f in CONTENT.glob(f"{pid}*.json"):
        if f.name == "papers.json":
            continue
        f.unlink()
        removed.append(str(f))
    d = PAPERS / pid
    if d.exists():
        shutil.rmtree(d)
        removed.append(str(d))
    return jsonify({"ok": True, "removed": removed})


@app.post("/api/render")
def api_render():
    payload = request.get_json(silent=True) or {}
    pid = (payload.get("id") or "").strip()
    theme = (payload.get("theme") or "ink").strip().lower()
    if theme not in THEMES:
        theme = "ink"
    versions = REND.load_versions(pid)
    if not versions:
        return jsonify({"error": "content not found"}), 404
    # 记录主题到各版本（后续渲染一致）
    for v, data in versions.items():
        if isinstance(data, dict):
            data["theme"] = theme
            REND.put_version(pid, v, data)
    out = PAPERS / pid
    base = versions.get("original") or next(iter(versions.values()), {})
    source_pdf = base.get("source_pdf", "")
    if source_pdf:
        src_pdf = CONTENT / source_pdf
        if src_pdf.exists():
            (out / source_pdf).parent.mkdir(parents=True, exist_ok=True)
            (out / source_pdf).write_bytes(src_pdf.read_bytes())
    doc_url = f"/source/{pid}.pdf" if source_pdf else ""
    src_url = base.get("source", "")
    if not src_url.startswith("http"):
        src_url = ""
    try:
        dest, size = REND.render_paper(versions, out, theme=theme,
                                       source_url=src_url, source_pdf=doc_url,
                                       doc_url=doc_url)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"渲染失败：{e}"}), 400
    return jsonify({"ok": True, "html": f"papers/{pid}/index.html",
                    "bytes": int(size), "versions": list(versions.keys())})


@app.get("/api/papers/<pid>/html")
def api_paper_html(pid):
    f = PAPERS / pid / "index.html"
    if not f.exists():
        return jsonify({"error": "render first"}), 404
    return send_file(f, mimetype="text/html")


@app.post("/api/upload")
def api_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "no file"}), 400
    pid = GEN.guess_id(file.filename)
    safe = pid + Path(file.filename).suffix.lower()
    dest = UPLOADS / safe
    file.save(dest)
    return jsonify({"ok": True, "path": f"uploads/{safe}", "pid": pid,
                    "source_pdf": f"uploads/{safe}", "name": file.filename})


@app.post("/api/new")
def api_new():
    payload = request.get_json(silent=True) or {}
    pid = (payload.get("id") or "").strip().lower()
    if not pid:
        pid = datetime.now().strftime("%Y%m%d%H%M")
    f = CONTENT / f"{pid}.json"
    if f.exists():
        return jsonify({"error": "exists"}), 409
    GEN.make_manual_template(f)
    return jsonify({"ok": True, "pid": pid})


# 静态：论文渲染产物
@app.get("/papers/<path:sub>")
def papers_static(sub):
    return send_from_directory(PAPERS, sub)


# 原始 PDF 伺服（论文页「PDF ↩」链接）
@app.get("/source/<pid>.pdf")
def source_pdf(pid):
    # 优先 content/<pid>/…，其次 content/uploads/<pdf>
    for cand in (CONTENT / "uploads" / f"{pid}.pdf",
                 CONTENT / f"{pid}.pdf",
                 CONTENT / "uploads" / f"{pid}.pdf"):
        if cand.exists():
            return send_file(cand, mimetype="application/pdf")
    # 兜底：从任意 version/meta 里读 source_pdf
    data = REND.load_versions(pid)
    src_pdf = ""
    if data:
        base = data.get("original") or next(iter(data.values()), {})
        src_pdf = base.get("source_pdf", "")
    if src_pdf:
        cand = CONTENT / src_pdf
        if cand.exists():
            return send_file(cand, mimetype="application/pdf")
    return jsonify({"error": "未找到原始 PDF"}), 404


def main():
    ap = argparse.ArgumentParser(description="浏览器版论文解读工作台")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    # 启动即内建静态论文库（生成 content/papers.json + 根 index.html）
    try:
        papers = SVR.build_library()
        SVR.build_index(papers)
        print(f"✓ 论文库链接：{url}/library（含 {len(papers)} 篇）")
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 构建论文库索引失败：{e}")
    print(f"▶ Web 工作台：{url}")
    print("  Ctrl+C 停止")
    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
