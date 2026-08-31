#!/usr/bin/env python3
"""
serve.py —— 本地预览服务器 + 论文库索引页

用法:
    python3 scripts/serve.py [--port 8000]
    python3 scripts/serve.py --build-only   # 只重建 index.html，不启动服务器

说明:
    - 扫描 content/*.json 生成 papers.json（论文库索引）
    - 渲染所有论文到 papers/<id>/index.html
    - 在根目录生成 index.html 论文库首页（搜索 + 筛选 + 卡片）
    - 启动 http.server 供浏览器预览
"""
from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"

LIBRARY_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>我的论文解读库</title>
<style>
:root{--accent:#b33a1e;--ink:#1c1b1a;--soft:#55524d;--faint:#8a867f;--line:#e7e3dc;--surface:#fff;--bg:#faf9f7}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:ui-sans-serif,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;padding:3.5rem 1.5rem 6rem;max-width:1040px;margin:0 auto}
h1{font-size:1.9rem;letter-spacing:-.01em;margin-bottom:.4rem}
.sub{color:var(--faint);font-size:.95rem;margin-bottom:2rem}
.toolbar{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.6rem;align-items:center}
input[type=search]{flex:1;min-width:220px;padding:.65rem 1rem;border:1px solid var(--line);border-radius:10px;font-size:.95rem;background:var(--surface)}
.filter{display:flex;gap:.4rem;flex-wrap:wrap}
.chip{padding:.4rem .85rem;border-radius:999px;border:1px solid var(--line);background:var(--surface);cursor:pointer;font-size:.85rem;color:var(--soft)}
.chip.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1.1rem}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:1.3rem;cursor:pointer;transition:transform .15s ease,box-shadow .15s ease;display:block;text-decoration:none;color:inherit}
.card:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,.07)}
.card .icon{font-size:1.5rem}
.card h3{font-size:1.05rem;margin:.6rem 0 .4rem;line-height:1.4;letter-spacing:-.01em}
.card .meta{font-size:.8rem;color:var(--faint);margin-bottom:.6rem}
.card .tags{display:flex;gap:.3rem;flex-wrap:wrap}
.card .tag{font-size:.7rem;padding:.15rem .5rem;border-radius:999px;background:#f0eee9;color:var(--soft)}
.card .vbadge{font-size:.68rem;padding:.12rem .42rem;border-radius:6px;font-weight:700;margin-left:.25rem}
.card .vbadge.v-original{background:#eef3f8;color:#2f5d8a}
.card .vbadge.v-detailed{background:#ede9fe;color:#7c3aed}
.empty{color:var(--faint);text-align:center;padding:3rem 0;font-size:.95rem}
.footer{color:var(--faint);font-size:.8rem;margin-top:3rem;text-align:center}
</style>
</head>
<body>
<h1>📚 我的论文解读库</h1>
<div class="sub">点开任意论文卡片阅读完整解读 · 由 paper-framework 生成</div>
<div class="toolbar">
  <input type="search" id="q" placeholder="🔍 搜索标题 / 标签 / 作者…" oninput="draw()">
  <div class="filter" id="filters"></div>
</div>
<div class="grid" id="grid"></div>
<div class="empty" id="empty" style="display:none">没有匹配的论文</div>
<div class="footer">paper-framework · 证据可追溯 · <span id="n"></span> 篇</div>
<script>
const PAPERS = __PAPERS__;
const allTags = [...new Set(PAPERS.flatMap(p=>p.tags||[]))].sort();
let active = "全部";
function draw(){
  const q=(document.getElementById('q').value||'').toLowerCase();
  const list=PAPERS.filter(p=>{
    const tagOk=active==="全部"||(p.tags||[]).includes(active);
    const hay=(p.title+" "+(p.tags||[]).join(" ")+" "+(p.meta||"")).toLowerCase();
    return tagOk && (!q||hay.includes(q));
  });
  const g=document.getElementById('grid');
  g.innerHTML=list.map(p=>`<a class=card href="${p.url}"><div class=icon>${p.icon||'📄'}</div><h3>${esh(p.title)}</h3><div class=meta>${esh(p.meta||'')}</div><div class=tags>${(p.versions||[]).map(v=>`<span class="vbadge v-${v}">${v==='detailed'?'详细':v==='original'?'原版':v}</span>`).join('')}${(p.tags||[]).map(t=>`<span class=tag>${esh(t)}</span>`).join('')}</div></a>`).join('');
  document.getElementById('empty').style.display=list.length?'none':'block';
  document.getElementById('n').textContent=list.length;
}
function esh(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML}
function drawFilters(){
  const f=document.getElementById('filters');
  f.innerHTML=["全部",...allTags].map(t=>`<button class="chip${t===active?' active':''}" onclick="active='${t}';drawFilters();draw()">${esh(t)}</button>`).join('');
}
drawFilters();draw();
</script>
</body>
</html>"""


def build_library() -> list[dict]:
    """扫描 content/*.json，按稳定 id 聚合各版本，每篇只出现一次。"""
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
        if pid not in grouped:
            grouped[pid] = {
                "id": pid,
                "title": data.get("title", pid),
                "meta": data.get("subtitle", "") or data.get("source", ""),
                "url": f"papers/{pid}/index.html",
                "icon": data.get("icon", "📄"),
                "tags": data.get("tags", []),
                "versions": [],
            }
            order.append(pid)
        g = grouped[pid]
        version = data.get("version") or (f.stem.split("__", 1)[1] if "__" in f.stem else "original")
        if version not in g["versions"]:
            g["versions"].append(version)
        if (not g["title"] or g["title"] == pid) and data.get("title"):
            g["title"] = data["title"]
    papers = [grouped[p] for p in order]
    (ROOT / "content" / "papers.json").write_text(
        json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
    return papers


def render_index_html(papers: list[dict]) -> str:
    """生成论文库首页的 HTML 字符串（不写盘），供 webapp 复用。"""
    return LIBRARY_TEMPLATE.replace("__PAPERS__", json.dumps(papers, ensure_ascii=False))


def build_index(papers: list[dict]):
    html = render_index_html(papers)
    (ROOT / "index.html").write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="本地预览 + 论文库（独立静态版）")
    ap.add_argument("--port", type=int, default=8020,
                    help="端口（默认 8020，避免与 webapp 的 8000 冲突）")
    ap.add_argument("--build-only", action="store_true")
    args = ap.parse_args()

    papers = build_library()
    build_index(papers)
    print(f"✓ 论文库索引：{len(papers)} 篇 → content/papers.json, index.html")

    if args.build_only:
        return 0

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

    with socketserver.TCPServer(("", args.port), Handler) as httpd:
        print(f"▶ 运行在 http://localhost:{args.port}")
        print("  Ctrl+C 停止")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
