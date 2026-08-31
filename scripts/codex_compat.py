#!/usr/bin/env python3
"""codex_compat.py —— 兼容 cc-switch 生成的模型目录（避免 codex 启动报缺字段）。

问题背景:
    cc-switch 会向 ~/.codex/config.toml 写入 model_catalog_json = "cc-switch-model-catalog.json"，
    但该目录缺 `base_instructions`、`supports_parallel_tool_calls` 等字段，导致新版 codex CLI 启动即报错：
        failed to parse model_catalog_json ... missing field `base_instructions`
    桌面客户端不受影响（它不读该文件）。

方案:
    - 从用户原目录读入，仅补齐缺失字段，写一份副本到 framework 的 .cache 下
      （不改动 ~/.codex/cc-switch-model-catalog.json）。
    - 通过 `-c model_catalog_json=<副本路径>` 传给 codex exec。
    - 附带 `--skip-git-repo-check` 以便在非 git 目录也能跑。
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"

# cc-switch 目录里常见的、codex 要求的模型级布尔/字符串字段
REQUIRED_DEFAULTS = {
    "base_instructions": "",
    "supports_parallel_tool_calls": True,
    "supports_functions": True,
    "supports_tools": True,
    "supports_streaming": True,
    "supports_reasoning": True,
    "supports_image_input": True,
    "supports_audio_input": True,
    "supports_vision": True,
    "supports_prompt_caching": True,
    "supports_automatic_compaction": True,
}

CATALOG_NAME = "cc-switch-model-catalog.json"


def _user_catalog_path() -> Path:
    """定位用户 ~/.codex/{CATALOG_NAME}；优先 HOME，其次从 config.toml 读出 path。"""
    home = Path(os.path.expanduser("~"))
    # 1) config.toml 里的 model_catalog_json 可能是绝对路径
    cfg = home / ".codex" / "config.toml"
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("model_catalog_json"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if os.path.isabs(val):
                    p = Path(val)
                    if p.exists():
                        return p
                else:
                    p = home / ".codex" / val
                    if p.exists():
                        return p
    # 2) 默认同目录
    default = home / ".codex" / CATALOG_NAME
    return default


def make_fixed_catalog() -> str:
    """生成为 codex 可用的目录副本，返回其路径（绝对路径）。"""
    src = _user_catalog_path()
    if not src.exists():
        # 没有用户目录，就不指定 override，让 codex 用自己默认
        return ""

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return ""

    models = data.get("models") if isinstance(data, dict) else data
    changed = 0
    if isinstance(models, list):
        for m in models:
            if isinstance(m, dict):
                for k, v in REQUIRED_DEFAULTS.items():
                    if k not in m:
                        m[k] = v
                        changed += 1
    elif isinstance(models, dict):
        for key, m in models.items():
            if isinstance(m, dict):
                for k, v in REQUIRED_DEFAULTS.items():
                    if k not in m:
                        m[k] = v
                        changed += 1
    if isinstance(data, dict):
        data["models"] = models

    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / f"{CATALOG_NAME}.fixed.json"
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # 记录是否发生修改（供日志提示）
    return str(dst)


def codex_cmd(args: list[str]) -> list[str]:
    """构建 codex exec 命令，自动注入兼容的 model_catalog_json override。

    - --json：输出 JSONL 事件流，便于 web/CLI 解析日志与正文
    - workspace-write：让 codex 能在项目目录内写 content.json（读取论文、提取图片后落盘）
    - --skip-git-repo-check：允许在非 git 目录运行
    """
    catalog = make_fixed_catalog()
    cmd = ["codex", "exec", *args, "--sandbox", "workspace-write",
           "--skip-git-repo-check", "--json"]
    if catalog:
        cmd += ["-c", f"model_catalog_json={catalog}"]
    return cmd


def codex_available() -> tuple[bool, str]:
    """返回 (codex 是否可执行, 说明)。用于前端状态提示。"""
    if shutil.which("codex") is None:
        return False, ""
    catalog = make_fixed_catalog()
    if catalog:
        return True, f"已自动生成兼容目录，沙箱 workspace-write"
    return True, "使用 codex 默认模型目录，沙箱 workspace-write"
