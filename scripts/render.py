#!/usr/bin/env python3
"""
render.py —— 将 content.json 渲染成自包含的单文件 index.html

用法:
    python3 render.py <id>
    python3 render.py <id> --theme simona            # 切换主题（默认 ink / simona）
    python3 render.py <id> --inline-assets           # 图片转 base64，完全单文件离线

说明:
    - 默认输出 papers/<id>/index.html
    - 默认图片引用 assets/<id>/... 相对路径（KaTeX 走 CDN）
    - --inline-assets 把图片内联为 base64，但 HTML 体积变大
    - theme 也可由 content.json 顶层 "theme" 字段指定
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

THEMES = ("ink", "simona")

# 主题显示名（用于页内切换器）。默认取 THEMES 顺序。
THEME_LABELS = {
    "ink": "ink",
    "simona": "simona",
}


def _style_path(theme: str) -> Path:
    """返回主题 CSS 路径；对 ink 是 style.css，其它是 style.<theme>.css。"""
    theme = theme if theme in THEMES else "ink"
    p = ROOT / "template" / (f"style.{theme}.css" if theme != "ink" else "style.css")
    if not p.exists():
        p = ROOT / "template" / "style.css"
    return p


def load_style(theme: str) -> str:
    """加载指定主题的 CSS 文本。"""
    return _style_path(theme).read_text(encoding="utf-8")


def load_all_themes() -> dict[str, str]:
    """返回 {主题名: CSS 文本}，用于页内多主题切换。"""
    return {t: _style_path(t).read_text(encoding="utf-8") for t in THEMES}


def _toolbar_css() -> str:
    return """<style id="ptoolbar-css">
.ptoolbar{position:fixed;top:16px;right:16px;z-index:9999;display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.ptool-row{display:flex;gap:4px;align-items:center;background:rgba(255,255,255,.92);backdrop-filter:blur(8px);border:1px solid #e7e3dc;border-radius:999px;padding:4px;box-shadow:0 2px 10px rgba(0,0,0,.08)}
.ptool-row .lbl{font-family:ui-sans-serif,-apple-system,"PingFang SC",sans-serif;font-size:.72rem;color:#8a867f;padding:0 .5rem}
.ptool-row button,.ptool-row .pbtn{border:none;background:transparent;font-family:ui-sans-serif,-apple-system,"PingFang SC",sans-serif;font-size:.82rem;font-weight:600;color:#8a867f;padding:.35rem .85rem;border-radius:999px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:.3rem}
.ptool-row button.active,.ptool-row .pbtn.active{background:#1c1b1a;color:#fff}
.ptool-row .pbtn:hover{background:#f0eee9;color:#1c1b1a}
.ptool-row .pbtn.active:hover{background:#1c1b1a;color:#fff}
.ptool-collapse{background:rgba(255,255,255,.92);backdrop-filter:blur(8px);border:1px solid #e7e3dc;border-radius:999px;padding:.4rem .8rem;box-shadow:0 2px 10px rgba(0,0,0,.08);color:#8a867f;cursor:pointer;font-size:.9rem;line-height:1}
.ptoolbar.hidden .ptool-row{display:none}
.ptoolbar.hidden .ptool-collapse{display:block}
@media(max-width:640px){.ptool-row .lbl{display:none}}
</style>"""


def _toolbar(theme: str, versions: list[str], active_version: str, source_url: str,
             source_pdf: str, doc_url: str) -> str:
    """右上角工具栏：主题 + 版本 + 打开原文/PDF + 收起。versions 为空则不显示版本段。"""
    theme_btns = "".join(
        f'<button data-set-theme="{t}" class="{"active" if t == theme else ""}">'
        f'{html.escape(THEME_LABELS.get(t, t))}</button>'
        for t in THEMES
    )
    theme_seg = f'<span class="lbl">主题</span>{theme_btns}'

    if len(versions) >= 2:
        version_labels = {"original": "原版", "detailed": "详细"}
        vbtns = "".join(
            f'<button data-set-version="{v}" class="{"active" if v == active_version else ""}">'
            f'{html.escape(version_labels.get(v, v))}</button>'
            for v in versions
        )
        version_seg = f'<span class="lbl">版本</span>{vbtns}'
    else:
        version_seg = ""

    source_links = []
    if source_url:
        source_links.append(f'<a class="pbtn" href="{html.escape(source_url)}" target="_blank" rel="noopener">原文 ↩</a>')
    if source_pdf:
        source_links.append(f'<a class="pbtn" href="{html.escape(source_pdf)}" target="_blank" rel="noopener">PDF ↩</a>')
    source_seg = "".join(source_links)

    return (
        f'<div class="ptoolbar" id="ptoolbar">'
        f'<div class="ptool-row">'
        f'{theme_seg}{version_seg}{source_seg}'
        f'<button onclick="togglePtool()" title="收起工具栏">▾</button>'
        f'</div>'
        f'<div class="ptool-collapse" onclick="togglePtool()" title="展开工具栏" style="display:none">🧰</div>'
        f'</div>'
        + (f'<script>var PDOC_URL={json.dumps(doc_url)};</script>' if doc_url else "")
    )


def _toolbar_js() -> str:
    return """<script>
(function(){
  function applyTheme(theme){
    document.querySelectorAll('style[data-theme]').forEach(function(s){
      s.disabled = (s.getAttribute('data-theme') !== theme);
    });
    document.querySelectorAll('.ptoolbar button[data-set-theme]').forEach(function(b){
      b.classList.toggle('active', b.getAttribute('data-set-theme') === theme);
    });
    try{ localStorage.setItem('paper-theme', theme);}catch(e){}
    document.body && document.body.setAttribute('data-paper-theme', theme);
  }
  function applyVersion(v){
    document.querySelectorAll('[data-version-block]').forEach(function(el){
      el.style.display = (el.getAttribute('data-version-block') === v) ? '' : 'none';
    });
    document.querySelectorAll('.ptoolbar button[data-set-version]').forEach(function(b){
      b.classList.toggle('active', b.getAttribute('data-set-version') === v);
    });
    try{ localStorage.setItem('paper-version', v);}catch(e){}
  }
  document.querySelectorAll('.ptoolbar button[data-set-theme]').forEach(function(b){
    b.addEventListener('click', function(){ applyTheme(b.getAttribute('data-set-theme')); });
  });
  document.querySelectorAll('.ptoolbar button[data-set-version]').forEach(function(b){
    b.addEventListener('click', function(){ applyVersion(b.getAttribute('data-set-version')); });
  });
  var savedT=null,savedV=null;
  try{ savedT=localStorage.getItem('paper-theme'); }catch(e){}
  try{ savedV=localStorage.getItem('paper-version'); }catch(e){}
  var meta=document.querySelector('meta[name=paper-theme]');
  applyTheme(savedT || (meta && meta.content) || 'ink');
  var ver=document.querySelector('meta[name=paper-version]');
  applyVersion(savedV || (ver && ver.content) || 'original');
})();
</script>
<script>
function togglePtool(){
  var bar=document.getElementById('ptoolbar');
  var row=bar.querySelector('.ptool-row');
  var cl=bar.querySelector('.ptool-collapse');
  if(row.style.display==='none'){row.style.display='';cl.style.display='none';}
  else{row.style.display='none';cl.style.display='block';}
}
</script>"""


# ---------- 版本发现 ----------

def put_version(pid: str, version: str, data: dict) -> Path:
    """把某版本数据写回 content/<pid>.json(original) 或 <pid>__<version>.json。"""
    out = ROOT / "content" / (f"{pid}.json" if version == "original" else f"{pid}__{version}.json")
    data.setdefault("id", pid)
    data.setdefault("version", version)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_versions(pid: str) -> dict[str, dict]:
    """扫描 content/<id>*.json，返回 {version: data}。默认版本(无 __ 后缀)记为 "original"。"""
    versions = {}
    # 默认/基础版本
    base = ROOT / "content" / f"{pid}.json"
    if base.exists():
        try:
            versions["original"] = json.loads(base.read_text(encoding="utf-8"))
        except Exception:
            pass
    # __ 后缀版本
    for f in (ROOT / "content").glob(f"{pid}__*.json"):
        v = f.stem.split("__", 1)[-1]
        if "meta" in v:
            continue
        try:
            versions[v] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    return versions




KATEX_SCRIPT = """<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body,{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}],throwOnError:false});"></script>"""


# ---------- mini markdown ----------

def md(text: str) -> str:
    """轻量 Markdown：加粗/斜体/行内代码/链接/行内公式（跳过 --- 与标题）。"""
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`([^`]+?)`", r"<code>\1</code>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    return t


def paras(text: str) -> str:
    parts = [p for p in text.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{md(p.strip())}</p>" for p in parts)


def evidence_html(ev: str | None) -> str:
    if not ev:
        return ""
    return f'<div class="evidence">原文依据：<code>{html.escape(ev)}</code></div>'


def resolve_asset(src: str, out_dir: Path, inline: bool) -> str:
    """把 content 里的相对路径解析到输出 html。inline=True 时转 base64。"""
    if not src:
        return ""
    if re.match(r"^(https?:|data:)", src):
        return src
    # 相对路径基于 content/ 目录解析
    cand = ROOT / "content" / src
    if cand.exists():
        content_bytes = cand.read_bytes()
    else:
        cand2 = ROOT / src
        if not cand2.exists():
            return ""  # 找不到则跳过该图（渲染时不输出 img）
        content_bytes = cand2.read_bytes()
    if inline:
        ext = cand.suffix.lower().lstrip(".") or "png"
        mime = {"jpg": "jpeg", "svg": "svg+xml"}.get(ext, ext)
        b64 = base64.b64encode(content_bytes).decode()
        return f"data:image/{mime};base64,{b64}"
    rel = Path("assets") / out_dir.name / Path(src).name
    target = out_dir / "assets" / out_dir.name / Path(src).name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content_bytes)
    return str(rel)


def _wrap_tex(tex: str) -> str:
    """确保公式文本带了 KaTeX 分隔符。已含 \$...\$ 或 \$\$...\$\$ 则原样返回，
    否则包成 display 模式 \$\$...\$\$。"""
    tex = tex.strip()
    if not tex:
        return ""
    # 已含 display 或 inline 分隔符
    if tex.startswith("$$") and tex.endswith("$$"):
        return tex
    if tex.count("$") >= 2 and "$" in tex:
        return tex
    return f"$${tex}$$"


def render_blocks(blocks: list, out_dir: Path, inline: bool) -> str:
    html_parts: list[str] = []
    for b in blocks:
        t = b.get("type")
        if t == "section":
            num = b.get("num", "")
            html_parts.append(
                f'<h2 class="sec">{f"<span class=num>{html.escape(num)}</span>" if num else ""}{md(b.get("title",""))}</h2>'
            )
        elif t == "sub":
            html_parts.append(f"<h3 class='sub'>{md(b.get('title',''))}</h3>")
        elif t == "p":
            html_parts.append(paras(b.get("text", "")))
        elif t == "list":
            ordered = b.get("ordered", False)
            tag = "ol" if ordered else "ul"
            items = "".join(f"<li>{md(i)}</li>" for i in b.get("items", []))
            html_parts.append(f"<{tag}>{items}</{tag}>")
        elif t == "concept":
            why = ""
            if b.get("why"):
                why = f'<div class="why"><div class="lbl">为什么重要</div>{paras(b["why"])}</div>'
            html_parts.append(
                f'<div class="concept"><div class="concept-title">{md(b.get("title",""))}</div>'
                f'<div class="concept-body">{paras(b.get("body",""))}</div>{why}</div>'
            )
        elif t == "insight":
            html_parts.append(f'<div class="insight">{md(b.get("text",""))}</div>')
        elif t == "figure":
            src = b.get("src", "")
            out_src = resolve_asset(src, out_dir, inline)
            if not out_src:
                p = b.get("caption", "")
                html_parts.append(paras(p))
                continue
            cap = md(b.get("caption", ""))
            ev = evidence_html(b.get("evidence"))
            html_parts.append(
                f'<figure class="paper-figure"><img src="{html.escape(out_src)}" alt="{html.escape(b.get("caption",""))}" loading="lazy">'
                f'<figcaption>{cap}{ev}</figcaption></figure>'
            )
        elif t == "formula":
            note = f'<div class="f-note">{paras(b.get("note",""))}</div>' if b.get("note") else ""
            ev = evidence_html(b.get("evidence"))
            tex = _wrap_tex(b.get("tex", ""))
            html_parts.append(
                f'<div class="formula-box"><div class="f-label">{html.escape(b.get("title","关键公式"))}</div>'
                f'<div>{tex}</div>{note}{ev}</div>'
            )
        elif t == "architecture":
            ev = evidence_html(b.get("evidence"))
            html_parts.append(
                f'<div class="architecture">{html.escape(b.get("text",""))}</div>{ev}'
            )
        elif t == "table":
            headers = b.get("headers", [])
            rows = b.get("rows", [])
            hls = {(r, c) for r, c in b.get("highlights", [])}
            thead = "<tr>" + "".join(f"<th>{html.escape(str(h))}</th>" for h in headers) + "</tr>"
            tbody = []
            for ridx, row in enumerate(rows):
                cells = []
                for cidx, cell in enumerate(row):
                    cls = []
                    if cidx > 0 and isinstance(cell, (int, float)):
                        cls.append("mono")
                    if (ridx, cidx) in hls:
                        cls.append("hl")
                    c = f"<td" + (f" class='{' '.join(cls)}'" if cls else "") + ">"
                    c += html.escape(str(cell)) + "</td>"
                    cells.append(c)
                tbody.append("<tr>" + "".join(cells) + "</tr>")
            caption = f'<div class="t-caption">{md(b.get("caption",""))}{evidence_html(b.get("evidence"))}</div>' if (b.get("caption") or b.get("evidence")) else ""
            html_parts.append(
                f'<div class="table-wrap"><table class="results"><thead>{thead}</thead>'
                f"<tbody>{''.join(tbody)}</tbody></table>{caption}</div>"
            )
        elif t == "verdict":
            html_parts.append(
                f'<div class="verdict"><div class="v-label">Verdict</div>{paras(b.get("text",""))}</div>'
            )
        elif t == "proscons":
            pros = "".join(f"<li>{md(i)}</li>" for i in b.get("pros", []))
            cons = "".join(f"<li>{md(i)}</li>" for i in b.get("cons", []))
            html_parts.append(
                '<div class="proscons">'
                f'<div class="box pros"><div class="h">优点</div><ul>{pros}</ul></div>'
                f'<div class="box cons"><div class="h">缺点 / 局限</div><ul>{cons}</ul></div>'
                "</div>"
            )
        elif t == "review":
            dims = "".join(_dim(d) for d in b.get("dimensions", []))
            overall = b.get("overall", "")
            overall_sub = b.get("overallSub", "")
            oh = (f'<div class="overall"><span class="o-lbl">整体评价</span>'
                  f'<span class="o-grade">{html.escape(overall)}</span>'
                  f'{"<span class=o-sub>"+md(overall_sub)+"</span>" if overall_sub else ""}</div>')
            summary = (f"<p>{md(b['summary'])}</p>" if b.get("summary") else "")
            html_parts.append(
                f'<div class="prof-review"><div class="h">博导审稿</div>{summary}'
                f'<div class="dim-list">{dims}</div>{oh}</div>'
            )
        elif t == "callout":
            kind = b.get("kind", "info")
            icon = {"info": "ℹ️", "warn": "⚠️", "tip": "💡"}.get(kind, "ℹ️")
            title = f'<div class="c-title">{md(b.get("title",""))}</div>' if b.get("title") else ""
            html_parts.append(
                f'<div class="callout {kind}"><span class="c-icon">{icon}</span>'
                f'<div>{title}{paras(b.get("text",""))}</div></div>'
            )
        elif t == "takeaway":
            html_parts.append(
                f'<div class="takeaway"><div class="h">一句话总结</div>'
                f'<div class="t">{md(b.get("text",""))}</div></div>'
            )
        else:
            html_parts.append(paras(str(b.get("text", json.dumps(b)))))
    return "\n\n".join(html_parts)


def _dim(d: dict) -> str:
    grade = d.get("grade", "mixed")
    gclass = f"grade-{grade}" if grade in ("strong", "weak", "mixed") else "grade-mixed"
    return (
        f'<div class="dim"><div class="dim-top"><span class="dim-name">{md(d.get("name",""))}</span>'
        f'<span class="dim-grade {gclass}">{html.escape(grade_labels.get(grade, grade))}</span></div>'
        f'<div class="dim-note">{paras(d.get("note",""))}</div></div>'
    )


grade_labels = {
    "strong": "强",
    "weak": "弱",
    "mixed": "中",
}


def render(data: dict, out: Path, theme: str = "ink", inline: bool = False) -> tuple[Path, str]:
    return render_paper({"original": data}, out, theme=theme, inline=inline)


def render_paper(versions: dict[str, dict], out: Path, theme: str = "ink",
                 inline: bool = False, source_url: str = "", source_pdf: str = "",
                 doc_url: str = "") -> tuple[Path, str]:
    """把一个论文的多个版本渲染成单文件 index.html。
    versions: {version: data}；优先取的默认版本是 "original"。"""
    theme = theme if theme in THEMES else "ink"
    themes_css = load_all_themes()
    out_dir = out
    out_dir.mkdir(parents=True, exist_ok=True)

    # 用第一个非空版本作为元信息兜底
    base = versions.get("original") or next(iter(versions.values()), {})
    meta = base.get("meta", base)
    title = base.get("title", meta.get("title", "Untitled"))
    subtitle = base.get("subtitle", "")
    authors = base.get("authors", "")
    affiliation = base.get("affiliation", "")
    doi = base.get("doi", "")
    date = base.get("date", "")
    tags = base.get("tags", [])

    tag_html = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in tags)
    sub_html = f'<div class="paper-subtitle">{md(subtitle)}</div>' if subtitle else ""

    meta_items = []
    if authors:
        meta_items.append(f"<span><strong>作者</strong> {md(authors)}</span>")
    if affiliation:
        meta_items.append(f"<span><strong>机构</strong> {md(affiliation)}</span>")
    source_text = base.get("source", "")
    if source_text:
        if source_text.startswith("http"):
            meta_items.append(f'<span><strong>来源</strong> <a href="{html.escape(source_text)}" target="_blank" rel="noopener">{md(source_text)}</a></span>')
        else:
            meta_items.append(f"<span><strong>来源</strong> {md(source_text)}</span>")
    if doi:
        meta_items.append(f'<span><strong>DOI</strong> <code>{html.escape(doi)}</code></span>')
    if date:
        meta_items.append(f"<span><strong>解读日期</strong> {html.escape(date)}</span>")
    meta_row = f'<div class="meta">{"".join(meta_items)}</div>' if meta_items else ""

    # 每个版本一个 data-version-block
    version_names = list(versions.keys())
    active_version = "original" if "original" in versions else version_names[0]
    version_body_html = []
    for v, vdata in versions.items():
        summary_html = f'<div class="paper-summary">{paras(vdata.get("summary",""))}</div>' if vdata.get("summary") else ""
        body = render_blocks(vdata.get("blocks", []), out_dir, inline)
        version_body_html.append(
            f'<div data-version-block="{v}" style="display:{"" if v == active_version else "none"}">'
            f'{summary_html}\n{body}</div>'
        )
    version_body = "\n".join(version_body_html)

    # 页内主题切换：每个主题一个 <style data-theme>，全部内嵌，JS 按需禁用
    if len(THEMES) > 1:
        style_blocks = []
        for t in THEMES:
            if (themes_css[t] or "").strip():
                style_blocks.append(f'<style data-theme="{t}">{themes_css[t]}</style>')
        styles_html = "\n".join(style_blocks)
    else:
        styles_html = f"<style>{themes_css[theme]}</style>"

    toolbar = _toolbar(theme, version_names, active_version, source_url, source_pdf, doc_url)

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="paper-theme" content="{theme}">
<meta name="paper-version" content="{active_version}">
<title>{html.escape(title)}</title>
{KATEX_SCRIPT}
{styles_html}
{_toolbar_css()}
</head>
<body>
{toolbar}
<div class="wrap">
<header class="paper-header">
  <div class="eyebrow">Paper Interpretation</div>
  <h1>{md(title)}</h1>{sub_html}
  {meta_row}
  <div class="tags">{tag_html}</div>
</header>
<hr class="rule">
<main>
{version_body}
</main>
<footer>生成于 {html.escape(date or "—")} · 由 paper-framework 渲染 · 证据可追溯({theme})</footer>
</div>
{_toolbar_js()}
</body>
</html>"""

    dest = out_dir / "index.html"
    dest.write_text(html_doc, encoding="utf-8")
    return dest, str(len(html_doc))


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染 content.json 为 index.html")
    ap.add_argument("content", help="content.json 或 content 目录下的 id")
    ap.add_argument("--theme", choices=THEMES, help="主题：ink（默认）/ simona；缺省用 content.json 的 theme 字段")
    ap.add_argument("--version", help="指定版本渲染（默认渲染全部版本并页内切换）")
    ap.add_argument("--out", help="输出目录，默认 papers/<id>")
    ap.add_argument("--inline-assets", action="store_true")
    args = ap.parse_args()

    src = Path(args.content)
    if not src.exists() and not src.suffix:
        src = ROOT / "content" / f"{src}.json"
        pid = src.stem
    else:
        if not src.exists():
            print(f"找不到 {src}", file=sys.stderr)
            return 1
        pid = src.stem

    if args.version:
        # 只渲染指定版本
        vpath = ROOT / "content" / (f"{pid}.json" if args.version == "original" else f"{pid}__{args.version}.json")
        if not vpath.exists():
            print(f"找不到版本文件 {vpath}", file=sys.stderr)
            return 1
        data = json.loads(vpath.read_text(encoding="utf-8"))
        theme = args.theme or data.get("theme", "ink")
        out = Path(args.out) if args.out else ROOT / "papers" / pid
        dest, size = render(data, out, theme=theme, inline=args.inline_assets)
        print(f"✓ 已渲染 → {dest}  [{theme}] ({size} bytes)")
        return 0

    versions = load_versions(pid)
    if not versions:
        print(f"没有找到 {pid} 的任何版本 content JSON", file=sys.stderr)
        return 1
    theme = args.theme or versions.get("original", {}).get("theme", "ink")
    base = versions.get("original") or next(iter(versions.values()), {})
    source_pdf = base.get("source_pdf", "")
    out = Path(args.out) if args.out else ROOT / "papers" / pid
    if source_pdf and not (out / source_pdf).exists():
        src_pdf = ROOT / "content" / source_pdf
        if src_pdf.exists():
            (out / source_pdf).parent.mkdir(parents=True, exist_ok=True)
            (out / source_pdf).write_bytes(src_pdf.read_bytes())
    doc_url = f"/source/{pid}.pdf" if source_pdf else ""
    src_url = base.get("source", "")
    if not src_url.startswith("http"):
        src_url = ""
    dest, size = render_paper(versions, out, theme=theme, inline=args.inline_assets,
                              source_url=src_url,
                              source_pdf=doc_url, doc_url=doc_url)
    print(f"✓ 已渲染 → {dest}  [{theme}] · 版本 {list(versions.keys())} ({size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
