#!/usr/bin/env python3
"""ContextAssembler：统一聚合三套记忆系统，为写作路径提供单一上下文入口。

聚合来源：
- long_term_context_manager：前情回顾 / 角色状态 / 活跃情节线 / 世界状态 / 里程碑
- story_graph_builder generate-context：图谱事实（伏笔 / 事件 / 关系）
- plot_rag_retriever 检索结果：相关历史片段
- foreshadowing_tracker.md：紧急 / 活跃伏笔清单
- story_graph.json cascade_pending：改纲后待清理的级联节点（连续性警告）

设计目标：任何写作路径（Beat Sheet / 普通章节 / 自动修复 / 改纲续写）只需调用
ContextAssembler.assemble() 一次，即可拿到结构化的全部连续性上下文，
杜绝"检索到了但某条路径没注入"的链路断裂。
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from long_term_context_manager import LongTermContextManager

# 各段渲染预算（中文字符），总量约 2500，避免写作提示词过度膨胀
BUDGETS: Dict[str, int] = {
    "recent_chapters": 500,
    "character_states": 500,
    "plot_threads": 300,
    "world_state": 400,
    "foreshadows": 400,
    "graph": 400,
    "rag": 800,
    "warnings": 300,
}

FORESHADOW_HEADER_RE = re.compile(r"^##\s*(.+)$")
FORESHADOW_SKIP_CELLS = {"ID", "伏笔内容", "---", ""}
FORESHADOW_SKIP_ROW = re.compile(r"^\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _strip_comments(text: str) -> str:
    return HTML_COMMENT.sub("", text)


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


@dataclass
class AssembledContext:
    """聚合结果：结构化 sections + 渲染好的连续性上下文块。"""

    sections: Dict[str, str] = field(default_factory=dict)
    prompt: str = ""
    source_stats: Dict[str, int] = field(default_factory=dict)


class ContextAssembler:
    """统一上下文聚合器（纯本地文件 + 现有组件，零新依赖）。"""

    def __init__(
        self,
        project_root: Path,
        chapter_no: int,
        rag_result: Optional[Dict[str, object]] = None,
        graph_context: Optional[Dict[str, object]] = None,
    ):
        self.project_root = Path(project_root)
        self.chapter_no = int(chapter_no)
        self.rag_result = rag_result if isinstance(rag_result, dict) else None
        self.graph_context = graph_context if isinstance(graph_context, dict) else None
        self.memory_dir = self.project_root / "00_memory"
        self.ltcm = LongTermContextManager(self.project_root, max_window_size=10)

    # ── 各来源采集 ──────────────────────────────────────────────

    def _collect_ltcm_sections(self) -> Dict[str, str]:
        sections: Dict[str, str] = {}
        try:
            ctx = self.ltcm.get_context_for_chapter(self.chapter_no)
        except Exception:
            ctx = None

        if ctx is not None:
            recent = []
            for s in ctx.recent_chapters[-3:]:
                recent.append(f"第{s.chapter_no}章：{_truncate(str(s.summary), 120)}")
            if recent:
                sections["recent_chapters"] = "\n".join(recent)

            threads = [t for t in ctx.plot_threads if t.status == "active"]
            if threads:
                sections["plot_threads"] = "\n".join(
                    f"- {_truncate(str(t.description), 80)}" for t in threads[:4]
                )

        # 角色状态：自解析 character_tracker 表格（与 plot_rag_retriever 的
        # 角色表格式一致；ltcm 的标题式解析与本项目实际格式不兼容）
        chars = self._collect_character_states_from_table()
        if chars:
            sections["character_states"] = chars

        world = self._collect_world_from_file()
        if world:
            sections["world_state"] = world
        return sections

    def _collect_character_states_from_table(self) -> str:
        """从 character_tracker.md 表格解析角色状态（兼容缺失/注释/分隔行）。"""
        tracker = self.memory_dir / "character_tracker.md"
        if not tracker.exists():
            return ""
        text = _strip_comments(tracker.read_text(encoding="utf-8", errors="ignore"))
        lines: List[str] = []
        for line in text.splitlines():
            if not line.strip().startswith("|"):
                continue
            if FORESHADOW_SKIP_ROW.match(line.strip()):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2 or cells[0] in {"姓名", "角色", "人物", "---", ""}:
                continue
            rest = [c for c in cells[1:] if c and c not in {"当前状态", "位置", "状态", "关系", "---"}]
            lines.append(f"- {cells[0]}" + (f"：{'、'.join(rest)}" if rest else ""))
        return "\n".join(lines[:6])

    def _collect_world_from_file(self) -> str:
        """从 world_state.md 提炼势力分布（宽容表格解析，兼容缺失文件）。"""
        world_file = self.memory_dir / "world_state.md"
        if not world_file.exists():
            return ""
        text = _strip_comments(world_file.read_text(encoding="utf-8", errors="ignore"))
        lines: List[str] = []
        for line in text.splitlines():
            if not line.strip().startswith("|"):
                continue
            if FORESHADOW_SKIP_ROW.match(line.strip()):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2 or cells[0] in {"势力名", "势力", "---", ""}:
                continue
            lines.append(f"- {cells[0]}：{'、'.join(c for c in cells[1:] if c and c not in {'---'})}")
        return "\n".join(lines[:6])

    def _collect_foreshadows(self) -> str:
        tracker = self.memory_dir / "foreshadowing_tracker.md"
        if not tracker.exists():
            return ""
        text = _strip_comments(tracker.read_text(encoding="utf-8", errors="ignore"))
        section = ""
        rows: List[str] = []
        for line in text.splitlines():
            m = FORESHADOW_HEADER_RE.match(line.strip())
            if m:
                section = m.group(1)
                continue
            if not line.strip().startswith("|") or FORESHADOW_SKIP_ROW.match(line.strip()):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 3 or cells[1] in FORESHADOW_SKIP_CELLS:
                continue
            # 仅保留紧急 / 活跃伏笔
            if "🔴" in section or "🟡" in section:
                rows.append(f"- [{cells[0]}] {cells[1]}（埋设于{cells[2]}）")
        return "\n".join(rows[:6])

    def _collect_rag(self) -> str:
        if not self.rag_result:
            return ""
        lines: List[str] = []
        for item in self.rag_result.get("retrieved", [])[:3]:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("chapter_file") or "")
            for p in (item.get("passages") or [])[:2]:
                if isinstance(p, dict) and p.get("text"):
                    lines.append(f"- {ref}：{_truncate(str(p['text']), 150)}")
        return "\n".join(lines)

    def _collect_graph(self) -> str:
        if not self.graph_context:
            return ""
        ctx_prompt = str(self.graph_context.get("context_prompt") or "").strip()
        return _truncate(ctx_prompt, BUDGETS["graph"])

    def _collect_warnings(self) -> str:
        warnings: List[str] = []
        graph_file = self.memory_dir / "story_graph.json"
        if graph_file.exists():
            try:
                graph = json.loads(graph_file.read_text(encoding="utf-8"))
                nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
                pending = [
                    n.get("id", "?")
                    for n in nodes
                    if isinstance(n, dict) and (n.get("cascade_pending") is True or n.get("status") == "cascade_pending")
                ]
                if pending:
                    warnings.append(f"知识图谱存在 {len(pending)} 个级联待清理节点（改纲影响），"
                                    f"写作时勿引用其旧设定：{', '.join(pending[:5])}")
            except Exception:
                pass
        return "\n".join(warnings)

    # ── 聚合与渲染 ──────────────────────────────────────────────

    def assemble(self) -> AssembledContext:
        sections: Dict[str, str] = {}
        sections.update(self._collect_ltcm_sections())
        sections["foreshadows"] = self._collect_foreshadows()
        sections["rag"] = self._collect_rag()
        sections["graph"] = self._collect_graph()
        sections["warnings"] = self._collect_warnings()
        # 结构稳定：所有 section 键恒存在（空段渲染时自然跳过）
        for key in ("recent_chapters", "character_states", "plot_threads",
                    "world_state", "foreshadows", "graph", "rag", "warnings"):
            sections.setdefault(key, "")

        prompt_parts: List[str] = []
        order = [
            ("recent_chapters", "前情回顾（最近章节摘要，保持连续性）"),
            ("character_states", "角色当前状态（不可违反）"),
            ("plot_threads", "活跃情节线"),
            ("foreshadows", "待处理伏笔（写前检查，勿提前回收）"),
            ("rag", "相关历史片段（RAG 检索）"),
            ("graph", "图谱事实（伏笔/事件/关系）"),
            ("world_state", "世界状态"),
            ("warnings", "连续性警告（级联待清理设定）"),
        ]
        for key, title in order:
            content = (sections.get(key) or "").strip()
            if not content:
                continue
            prompt_parts.append(f"## {title}\n{_truncate(content, BUDGETS[key])}")

        prompt = ""
        if prompt_parts:
            prompt = "【连续性上下文】\n" + "\n\n".join(prompt_parts)

        stats = {k: len(v) for k, v in sections.items() if v}
        return AssembledContext(sections=sections, prompt=prompt, source_stats=stats)


def main() -> int:
    """CLI 入口：调试用。python3 context_assembler.py --project-root <路径> --chapter <N>"""
    import argparse

    p = argparse.ArgumentParser(description="聚合项目连续性上下文（调试用）")
    p.add_argument("--project-root", required=True)
    p.add_argument("--chapter", type=int, required=True)
    args = p.parse_args()

    assembled = ContextAssembler(Path(args.project_root), args.chapter).assemble()
    print(json.dumps({
        "ok": True,
        "chapter_no": args.chapter,
        "sections": {k: len(v) for k, v in assembled.sections.items()},
        "prompt_chars": len(assembled.prompt),
        "prompt": assembled.prompt,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
