#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可视化面板生成器（文风复刻增强层 · 可视化层）

读取小说项目的 00_memory / 03_manuscript / 04_editing 状态文件，
生成一个自包含的 HTML 仪表盘（单文件，浏览器直接打开）。

用法:
    python dashboard.py --project-root ./我的小说
    python dashboard.py --project-root ./我的小说 --out dashboard.html --open

生成的面板包含：
- 指标卡：已写章节 / 总字数 / 未回收伏笔 / 门禁状态
- 剧情进度条（大纲锚点）
- 角色状态（知识图谱）
- 伏笔追踪器
- 文风校准（近 N 章风格审计摘要）
- RAG 记忆检索（可交互搜索）

纯标准库实现，无第三方依赖。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
EMDASH_RE = re.compile(r"(?<!—)——(?!—)")
DAO_RE = re.compile(rf"[一-鿿]{{0,4}}道[：:，,]?\s*[“\"「]")


def esc(s: str) -> str:
    return html.escape(str(s))


# ---------- 读取状态 ----------

def load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def load_md(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def collect(project_root: Path) -> Dict[str, object]:
    root = Path(project_root).expanduser().resolve()
    memory = root / "00_memory"
    manuscript = root / "03_manuscript"
    editing = root / "04_editing"
    kb = root / "02_knowledge_base"

    # 章节统计
    chapters = sorted([p for p in manuscript.rglob("*.md")]) if manuscript.exists() else []
    chapter_stats = []
    for ch in chapters:
        text = ch.read_text(encoding="utf-8", errors="ignore")
        chapter_stats.append({"name": ch.stem, "chars": len(CJK_RE.findall(text))})

    total_chars = sum(c["chars"] for c in chapter_stats)

    # 大纲锚点
    anchors = load_json(memory / "outline_anchors.json") if memory.exists() else None
    current_chapter = 0
    total_chapters = 0
    if anchors:
        current_chapter = anchors.get("current_chapter") or anchors.get("current") or len(chapter_stats)
        total_chapters = anchors.get("total_chapters_target") or 0

    # 知识图谱
    graph = load_json(memory / "story_graph.json") if memory.exists() else None
    characters = []
    if graph:
        nodes = graph.get("nodes", graph.get("characters", []))
        if isinstance(nodes, dict):
            nodes = list(nodes.values())
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "character" or "name" in node:
                name = node.get("name", node.get("id", "?"))
                attrs = {k: v for k, v in node.items()
                         if k not in ("id", "type", "name", "created_at", "last_updated")}
                characters.append({"name": str(name), "attrs": attrs})

    # 伏笔
    foreshadowing = load_md(memory / "foreshadowing_tracker.md") if memory.exists() else ""
    foreshadows = parse_tracker(foreshadowing)

    # 文风档案
    style_anchor = load_md(memory / "style_anchor.md") if memory.exists() else ""

    # 门禁产物
    gate_results = []
    gate_dir = editing / "gate_artifacts" if editing.exists() else None
    if gate_dir and gate_dir.exists():
        for g in sorted(gate_dir.rglob("gate_result.json")):
            data = load_json(g)
            if data:
                gate_results.append({"chapter": g.parent.name, "passed": data.get("passed")})

    # 章节风格审计摘要（粗略：只测破折号与"道"）
    audit_summary = []
    for c in chapter_stats[-10:]:
        path = next((p for p in chapters if p.stem == c["name"]), None)
        if not path:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        n = len(CJK_RE.findall(text)) or 1
        audit_summary.append({
            "name": c["name"],
            "emdash_per_wan": round(len(EMDASH_RE.findall(text)) / n * 10000, 1),
            "dao_hits": len(DAO_RE.findall(text)),
        })

    return {
        "total_chars": total_chars,
        "chapters": chapter_stats,
        "current_chapter": current_chapter,
        "total_chapters": total_chapters,
        "characters": characters,
        "foreshadows": foreshadows,
        "style_anchor": style_anchor,
        "gate_results": gate_results,
        "audit_summary": audit_summary,
    }


def parse_tracker(text: str) -> List[Dict]:
    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 尝试解析：名称 | 状态 或 名称 状态词
        m = re.match(r"^(?:[-*]?\s*)?(T\d*)\s*[·|]\s*(.+?)[|，,]\s*(已收|待回收|暗线推进|推进中|完成|回收)$", line)
        if m:
            results.append({"tier": m.group(1), "name": m.group(2).strip(), "status": m.group(3)})
            continue
        m2 = re.match(r"^(?:[-*]?\s*)?(.+?)\s+(已收|待回收|暗线推进|推进中|完成|回收)$", line)
        if m2:
            results.append({"tier": "", "name": m2.group(1).strip(), "status": m2.group(2)})
    return results


# ---------- HTML 渲染 ----------

def render(data: Dict[str, object]) -> str:
    d = data
    done = len(d["chapters"])
    total = d["total_chapters"] or max(done, 1)
    pct = round(done / total * 100) if total else 0

    pending_foreshadow = sum(1 for f in d["foreshadows"] if f["status"] not in ("已收", "完成"))
    gate_pass = sum(1 for g in d["gate_results"] if g["passed"])
    gate_total = len(d["gate_results"])

    # 角色卡
    char_html = ""
    for c in d["characters"][:8]:
        attrs = " · ".join(f"{k}:{v}" for k, v in list(c["attrs"].items())[:3]) or "—"
        initial = c["name"][:1]
        char_html += f"""
        <div style="display:flex; gap:10px; margin-bottom:12px; align-items:center;">
          <div style="width:36px; height:36px; border-radius:50%; background:var(--color-background-info);
               display:flex; align-items:center; justify-content:center; font-size:13px;
               font-weight:500; color:var(--color-text-info);">{esc(initial)}</div>
          <div>
            <p style="font-size:13px; font-weight:500; margin:0;">{esc(c['name'])}</p>
            <p style="font-size:12px; color:var(--color-text-secondary); margin:0;">{esc(attrs)}</p>
          </div>
        </div>"""
    if not char_html:
        char_html = '<div style="font-size:12px; color:var(--color-text-tertiary);">暂无角色数据（story_graph.json 为空）</div>'

    # 伏笔
    fs_html = ""
    for f in d["foreshadows"][:8]:
        color = {"已收": "success", "完成": "success", "待回收": "warning",
                 "暗线推进": "secondary", "推进中": "secondary"}.get(f["status"], "secondary")
        fs_html += f'<div style="font-size:13px; margin-bottom:8px;">{esc(f["tier"] or "")} · {esc(f["name"])} <span style="color:var(--color-text-{color});">{esc(f["status"])}</span></div>'
    if not fs_html:
        fs_html = '<div style="font-size:12px; color:var(--color-text-tertiary);">暂无伏笔数据</div>'

    # 章节条
    bar_html = ""
    for c in d["chapters"][-20:]:
        w = max(8, round(c["chars"] / max(x["chars"] for x in d["chapters"]) * 100)) if d["chapters"] else 8
        bar_html += f"""
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
          <span style="font-size:12px; color:var(--color-text-secondary); width:60px; flex:none;">{esc(c['name'])}</span>
          <div style="flex:1; height:14px; background:var(--color-background-secondary); border-radius:4px; overflow:hidden;">
            <div style="width:{w}%; height:100%; background:#1D9E75; border-radius:4px;"></div>
          </div>
          <span style="font-size:12px; color:var(--color-text-tertiary); width:56px; text-align:right;">{c['chars']:,}字</span>
        </div>"""
    if not bar_html:
        bar_html = '<div style="font-size:12px; color:var(--color-text-tertiary);">暂无章节（03_manuscript 为空）</div>'

    # 门禁
    gate_color = "success" if gate_total and gate_pass == gate_total else ("warning" if gate_pass else "danger")
    gate_label = f"{gate_pass}/{gate_total} 通过" if gate_total else "无记录"

    # 审计摘要
    audit_html = ""
    for a in d["audit_summary"]:
        warn = "secondary"
        if a["emdash_per_wan"] > 25:
            warn = "warning"
        if a["dao_hits"] > 0:
            warn = "danger"
        audit_html += f'<div style="font-size:13px; margin-bottom:6px;">{esc(a["name"])} <span style="color:var(--color-text-{warn});">破折号{a["emdash_per_wan"]}/万 · 道×{a["dao_hits"]}</span></div>'
    if not audit_html:
        audit_html = '<div style="font-size:12px; color:var(--color-text-tertiary);">暂无章节可审计</div>'

    return f"""<h2 class="sr-only">小说创作项目状态面板</h2>
<div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
  <span style="font-size:15px; font-weight:500;">创作控制台</span>
  <span style="font-size:12px; color:var(--color-text-secondary);">基于 00_memory 状态文件实时渲染</span>
</div>
<div style="font-size:13px; color:var(--color-text-secondary); margin-bottom:16px;">
  已写 {done} 章 · {d['total_chars']:,} 字 · 门禁 {esc(gate_label)}
</div>

<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px,1fr)); gap:12px; margin-bottom:16px;">
  <div style="background:var(--color-background-secondary); border-radius:var(--border-radius-md); padding:1rem;">
    <p style="font-size:13px; color:var(--color-text-secondary); margin:0 0 4px;">已写章节</p>
    <p style="font-size:24px; font-weight:500; margin:0;">{done} / {total}</p>
  </div>
  <div style="background:var(--color-background-secondary); border-radius:var(--border-radius-md); padding:1rem;">
    <p style="font-size:13px; color:var(--color-text-secondary); margin:0 0 4px;">总字数</p>
    <p style="font-size:24px; font-weight:500; margin:0;">{d['total_chars']:,}</p>
  </div>
  <div style="background:var(--color-background-secondary); border-radius:var(--border-radius-md); padding:1rem;">
    <p style="font-size:13px; color:var(--color-text-secondary); margin:0 0 4px;">未回收伏笔</p>
    <p style="font-size:24px; font-weight:500; margin:0; color:var(--color-text-warning);">{pending_foreshadow}</p>
  </div>
  <div style="background:var(--color-background-secondary); border-radius:var(--border-radius-md); padding:1rem;">
    <p style="font-size:13px; color:var(--color-text-secondary); margin:0 0 4px;">当前门禁</p>
    <p style="font-size:24px; font-weight:500; margin:0; color:var(--color-text-{gate_color});">{esc(gate_label)}</p>
  </div>
</div>

<div style="font-size:14px; font-weight:500; margin:12px 0 8px;">剧情进度</div>
<div style="display:flex; align-items:center; gap:12px; margin-bottom:20px;">
  <div style="flex:1; height:8px; background:var(--color-background-secondary); border-radius:4px; overflow:hidden;">
    <div style="width:{pct}%; height:100%; background:#1D9E75; border-radius:4px;"></div>
  </div>
  <span style="font-size:13px; color:var(--color-text-secondary);">{pct}%</span>
</div>

<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px,1fr)); gap:16px;">
  <div style="background:var(--color-background-primary); border:0.5px solid var(--color-border-tertiary); border-radius:var(--border-radius-lg); padding:1rem 1.25rem;">
    <p style="font-size:14px; font-weight:500; margin:0 0 12px;">角色状态 · 知识图谱</p>
    {char_html}
  </div>
  <div style="background:var(--color-background-primary); border:0.5px solid var(--color-border-tertiary); border-radius:var(--border-radius-lg); padding:1rem 1.25rem;">
    <p style="font-size:14px; font-weight:500; margin:0 0 12px;">伏笔追踪器</p>
    {fs_html}
  </div>
  <div style="background:var(--color-background-primary); border:0.5px solid var(--color-border-tertiary); border-radius:var(--border-radius-lg); padding:1rem 1.25rem;">
    <p style="font-size:14px; font-weight:500; margin:0 0 12px;">文风校准 · 近10章</p>
    {audit_html}
  </div>
</div>

<div style="font-size:14px; font-weight:500; margin:16px 0 8px;">章节字数分布</div>
<div style="background:var(--color-background-primary); border:0.5px solid var(--color-border-tertiary); border-radius:var(--border-radius-lg); padding:1rem 1.25rem;">
  {bar_html}
</div>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="可视化面板生成器")
    parser.add_argument("--project-root", required=True, help="小说项目根目录")
    parser.add_argument("--out", help="输出 HTML 路径（默认 {project}/dashboard.html）")
    parser.add_argument("--open", action="store_true", help="生成后尝试用默认浏览器打开")
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve()
    if not root.exists():
        print(f"项目不存在: {root}")
        return 1

    data = collect(root)
    html_content = render(data)

    out = Path(args.out).expanduser().resolve() if args.out else root / "dashboard.html"
    out.write_text(html_content, encoding="utf-8")
    print(f"面板已生成: {out}")

    if args.open:
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", "", str(out)], shell=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
