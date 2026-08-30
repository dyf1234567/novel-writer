#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多 Agent 四官审计 · 任务生成器（写后自动链路）

把 references/multi-agent-audit-protocol.md 里"四官并行审计"这一协议步骤，
接入 /继续写 的「门禁通过」之后：每章门禁一过，自动为 文风官 / 结构官 / 人物官 / 质量官
各生成一份**自包含**的审计任务文件（角色卡全文 + 任务简报 + 本官检查清单 +
角色人格层保护 + 输出格式 + 约束），落到
  04_editing/gate_artifacts/<chapter_id>/four_official/
供主 Agent（WorkBuddy 通用子代理）直接读取并派发。

设计要点
--------
- 本脚本**只生成任务文件**，不派发子代理（派发是 AI 编排层 / 主 Agent 的职责，
  与 cross_agent_reviewer.py 的"生成 task/prompt 不 dispatch"保持一致）。
- 子代理请先用 Read 工具读取待审正文全文（避免截断、保证审计质量）。
- 角色人格层（00_memory/character_persona.md）未建立时，文风官会被指示把
  "叙事人格是否漂移" 判为「无法判定（人格层未建立）」并建议用户建立——
  系统只提醒、不代填，避免 AI 把被模仿作者的角色口头禅套到用户主角身上。

子命令
------
1. generate  — 生成四官审计任务（门禁通过后调用）
2. record    — 记录四官审计汇总结果（主 Agent 汇总后回写产物）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (  # noqa: E402
    ensure_dir,
    load_json,
    read_text,
    save_json,
    slugify,
    write_text,
)

# style_fewshot 提供：解析风格作者 + 检查人格层（复用，避免重复实现）
try:
    from style_fewshot import (  # noqa: E402
        check_project_persona,
        resolve_style_author,
    )
except Exception:  # pragma: no cover - 兜底
    check_project_persona = None  # type: ignore
    resolve_style_author = None  # type: ignore


# =============================================================================
# 四官角色卡（执行源；references/four-official-roles-workbuddy.md 为同款文档版）
# =============================================================================

ROLE_KEYS = ["wenfeng", "jiegou", "renwu", "zhiliang"]
ROLE_NAMES = {
    "wenfeng": "文风官",
    "jiegou": "结构官",
    "renwu": "人物官",
    "zhiliang": "质量官",
}

ROLE_INTRO = {
    "wenfeng": (
        "你是长篇小说「文风保真度」审计官。你的唯一职责：判断本章文字是否忠实复刻了"
        "目标作者的文笔语感，以及是否发生了「叙事人格漂移」。你不评价情节好坏。"
    ),
    "jiegou": (
        "你是资深小说结构编辑 / 伏笔管理审计官。你的唯一职责：检查本章的叙事结构、"
        "大纲覆盖度、伏笔与逻辑链完整性。你不评价文笔美不美。"
    ),
    "renwu": (
        "你是人物塑造一致性审计官。你的唯一职责：核对本章角色言行是否符合其设定档案，"
        "有无性格漂移、动机不成立或设定吃书。你不评价结构。"
    ),
    "zhiliang": (
        "你是严格的文字质量审计官，专抓「AI 写作痕迹」与节奏问题。你的唯一职责："
        "最小化地标记 AI 味与节奏瑕疵。你不评价情节与人物。"
    ),
}

ROLE_CHECKLIST = {
    "wenfeng": [
        "对话动词体系是否符合目标作者（如：多用「说」，少用「道/言/道了一句」）",
        "短句呼吸节奏（长短句是否交替，是否一气到底或碎成一地）",
        "吐槽渗透叙述的程度是否自然（不硬拗、不为了俏而俏）",
        "比喻密度（约每千字 1 个；过密显堆砌、过疏显干瘪，均记 P1）",
        "泪点不解释原则（情绪是否靠行动/细节承载，而非直白说明）",
        "标点情绪（省略号/破折号是否克制地为情绪服务）",
        "破折号是否滥用（每千字超过 3 个即记 P1）",
        "⚠️ 叙事人格漂移专项（P1 红线，见下方「角色人格层保护」）",
    ],
    "jiegou": [
        "原剧本 / 大纲事件覆盖度（本章是否完成了 novel_plan 分配的情节任务）",
        "关键设定零偏差（如单尾非九尾、距离 / 能力边界等硬设定）",
        "章末悬念强度（是否留了自然钩子，钩子是否生硬）",
        "伏笔埋设自然度（不硬塞、不抢戏）",
        "A/B/C 节奏配额是否越界（参考 pacing / outline_anchor）",
        "有无提前揭底（不该现在揭的设定是否泄露）",
        "⚠️ 逻辑链完整性硬约束（必查，见下方专项）",
    ],
    "renwu": [
        "言行是否符合 character_tracker.md 设定？有无性格漂移",
        "吐槽自然度 / 密度（是否符合该角色人设，而非「作者标配」吐槽）",
        "关键抉择动机是否成立（站得住脚，不是为推剧情而降智）",
        "重大事件反应是否符合人设（崩溃 / 冷笑 / 沉默是否对味）",
        "伏笔不越界（角色行为不提前泄露后续走向）",
        "对照 character_tracker.md 的当前位置 / 状态 / 能力边界，逐项核实",
    ],
    "zhiliang": [
        "破折号滥用（每千字超 3 个即记 P1）",
        "「不是 X 而是 Y」句式高频出现",
        "AI 高频词（中文小说专属词表：不禁 / 仿佛 / 宛如 / 映入眼帘 / 心中暗道 / 沉声道 / "
        "脸色一变 / 嘴角微扬 / 勾起一抹弧度 / 不由自主 / 只见 / 目光如炬 等，用行动替代状态）",
        "弱化副词堆叠（微微 / 淡淡 / 缓缓 / 轻轻 / 悄然 / 默默 / 隐隐，每千字超 3 个即超标）",
        "机械排比（凑三个一组制造全面感）",
        "tell-don't-show（用说明替代呈现）",
        "场景过度描写（信息密度低的长段环境铺陈）",
        "说明书式对白（对话像在交代设定而非人在说话）",
        "节奏检查：段落错落、开场 300 字抓人力、情感起伏曲线是否单调",
    ],
}

LOGIC_HARD_CONSTRAINT = """⚠️ 逻辑链完整性硬约束（必查）
- 每个动作 / 反应是否有因果支撑？（为什么成功 / 失败 / 服从？）
- 时间、空间、人物状态是否自洽？（有没有「瞬移」或凭空出现的信息？）
- 有没有「读者会问为什么」的缝隙？（如「命令之前失败，为何这次成功」）
- 前后信息是否矛盾？（前文没交代的东西不能突然出现）
→ 任何逻辑缝隙记 P1，并在报告中给出「建议补的因果背书」。"""

OUTPUT_FORMAT = """## 输出格式（严格遵守）
```
# 四官审计 · {role_name} · 第{chapter}章
## 综合评分（0-100）
## 逐条判定（达标 / 偏差 + 证据[引原文] + 修改建议）
## P0 / P1 / P2 问题清单（每条注明段落位置）
## 一句话结论
```
评分标准：A+≥90 直接放行；A/A- 82-89 修 P0/P1；B/B- 70-81 修 P0/P1 必要时补写；C<70 大改重写。
约束：这是研究任务，不要修改任何文件。报告控制在 600 字以内。"""


# =============================================================================
# 上下文解析
# =============================================================================

def _resolve_book_title(project_root: Path, override: Optional[str]) -> str:
    if override and override.strip():
        return override.strip()
    # 1) 项目配置
    cfg = project_root / ".novel_writer_config.yaml"
    if cfg.exists():
        txt = read_text(cfg)
        m = re.search(r"(?:book_title|title)\s*[:=]\s*['\"]?([^'\"\n]+)", txt)
        if m:
            return m.group(1).strip().strip("'\"")
    # 2) novel_state.md 书名/作品名
    state = project_root / "00_memory" / "novel_state.md"
    if state.exists():
        for line in read_text(state).splitlines():
            m = re.search(r"(?:书名|作品名|title)\s*[：:]\s*(.+)", line)
            if m:
                return m.group(1).strip().strip("'\"")
    # 3) 项目目录名（多数项目以书名命名目录）
    if project_root.name and project_root.name not in (".", ".."):
        return project_root.name
    # 4) novel_plan.md 第一个一级标题（模板标题兜底）
    plan = project_root / "00_memory" / "novel_plan.md"
    if plan.exists():
        for line in read_text(plan).splitlines():
            s = line.strip()
            if s.startswith("# ") and len(s) > 2:
                return s[2:].strip()
    return project_root.name


def _resolve_author(project_root: Path, override: Optional[str]) -> Dict[str, Any]:
    """返回 {'slug','display','ok'}。无模仿对象时 slug=None。"""
    slug = None
    if resolve_style_author is not None:
        try:
            slug = resolve_style_author(project_root, override)
        except Exception:
            slug = None
    if not slug:
        return {"slug": None, "display": "（本项目原创文风，无模仿对象）", "ok": False}
    display = slug
    idx = SCRIPT_DIR.parent / "authors" / slug / "index.json"
    if idx.exists():
        data = load_json(idx)
        if isinstance(data, dict) and data.get("name"):
            display = str(data["name"])
    return {"slug": slug, "display": display, "ok": True}


def _persona_block(project_root: Path) -> Dict[str, Any]:
    """返回人格层状态 + 用于注入 prompt 的文本块。"""
    if check_project_persona is None:
        return {
            "established": False,
            "path": str(project_root / "00_memory" / "character_persona.md"),
            "missing": ["口头禅", "吐槽功能", "紧张时的反应", "OOC 红线"],
            "block": (
                "## ⚠️ 角色人格层未建立\n"
                "（style_fewshot 模块不可用，无法判定。请确认 character_persona.md 是否存在。）\n"
                "文风官：将「叙事人格是否漂移」判为「无法判定（人格层未建立）」，"
                "并在报告末尾建议用户建立 00_memory/character_persona.md。"
            ),
        }
    info = check_project_persona(project_root)
    pfile = project_root / "00_memory" / "character_persona.md"
    if info.get("established"):
        content = read_text(pfile)
        block = (
            "## 角色人格层（已建立，作为本官检查基准）\n"
            "以下是本项目**自己角色**的声音设定，文风复刻时须以此约束，"
            "不得让 AI 把被模仿作者的角色口头禅 / 说话方式套到这些角色身上：\n\n"
            f"{content.strip()}\n\n"
            "文风官专项：逐条核对本章对话吐槽是「本作品角色专属人格」还是"
            "「参考作者常见人格 / 参考作主角人格」；出现「吐槽无目的 / 自嘲示弱 / "
            "口吻像参考作主角」即判 P1 人格漂移。"
        )
    else:
        block = (
            "## ⚠️ 角色人格层未建立\n"
            f"  待填字段：{', '.join(info.get('missing', []))}\n"
            f"  请编辑：{info.get('path')}\n"
            "（系统只提醒、不代填，以免 AI 把被模仿作者的角色口头禅套到你的主角身上。）\n\n"
            "文风官专项：将「叙事人格是否漂移」判为「无法判定（人格层未建立）」，"
            "并在报告末尾建议用户建立 00_memory/character_persona.md。"
        )
    info["block"] = block
    return info


# =============================================================================
# 任务生成
# =============================================================================

def _build_prompt(
    role_key: str,
    *,
    book_title: str,
    chapter: int,
    chapter_title: str,
    chapter_file: str,
    project_root: str,
    author: Dict[str, Any],
    persona: Dict[str, Any],
) -> str:
    role_name = ROLE_NAMES[role_key]
    brief = (
        "## 任务简报\n"
        f"- 书名：《{book_title}》\n"
        f"- 审计章节：第 {chapter} 章（{chapter_title or '未命名'}）\n"
        f"- 待审正文（请用 Read 工具读取**全文**）：{chapter_file}\n"
        f"- 风格作者（本作文风复刻对象）：{author['display']}"
        f"（slug: {author['slug'] or '无'}）\n"
        f"- 文风锚点：{project_root}/00_memory/style_anchor.md\n"
        f"- 角色档案：{project_root}/00_memory/character_tracker.md\n"
        f"- 大纲：{project_root}/00_memory/novel_plan.md\n"
        f"- 项目根目录：{project_root}\n"
    )
    checklist = "\n".join(f"{i}. {c}" for i, c in enumerate(ROLE_CHECKLIST[role_key], 1))
    logic = LOGIC_HARD_CONSTRAINT if role_key == "jiegou" else ""
    fmt = OUTPUT_FORMAT.format(role_name=role_name, chapter=chapter)
    return (
        f"# 四官审计任务 · {role_name} · 第{chapter}章\n\n"
        f"## 角色卡（你是谁）\n{ROLE_INTRO[role_key]}\n\n"
        f"{brief}\n"
        f"## 本官核心检查清单\n{checklist}\n\n"
        f"{logic}\n"
        f"{persona['block']}\n\n"
        f"{fmt}\n"
    )


def cmd_generate(args: argparse.Namespace) -> Dict[str, Any]:
    project_root = Path(args.project_root).expanduser().resolve()
    chapter_file = Path(args.chapter_file)
    if not chapter_file.is_absolute():
        chapter_file = project_root / chapter_file
    if not chapter_file.exists():
        return {
            "ok": False, "command": "generate",
            "error": f"章节文件不存在: {chapter_file}",
        }

    chapter = args.chapter if args.chapter and args.chapter > 0 else 0
    chapter_title = chapter_file.stem
    if chapter == 0:
        m = re.search(r"第(\d+)章", chapter_file.name)
        chapter = int(m.group(1)) if m else 0
    # 去掉文件名前缀「第N章[-_ ]」，只留章节本名（如「第002章-人」→「人」）
    _prefix = re.match(r"^第\d+章[\s\-_]*", chapter_title)
    if _prefix:
        _stripped = chapter_title[_prefix.end():].strip(" -_")
        if _stripped:
            chapter_title = _stripped

    book_title = _resolve_book_title(project_root, args.book_title)
    author = _resolve_author(project_root, args.style_author)
    persona = _persona_block(project_root)

    gate_dir = project_root / "04_editing" / "gate_artifacts" / slugify(chapter_file.stem)
    four_dir = gate_dir / "four_official"
    ensure_dir(four_dir)

    tasks: List[Dict[str, Any]] = []
    for role_key in ROLE_KEYS:
        prompt = _build_prompt(
            role_key,
            book_title=book_title,
            chapter=chapter,
            chapter_title=chapter_title,
            chapter_file=str(chapter_file),
            project_root=str(project_root),
            author=author,
            persona=persona,
        )
        prompt_path = four_dir / f"{role_key}_prompt.md"
        write_text(prompt_path, prompt)
        task = {
            "role": ROLE_NAMES[role_key],
            "role_key": role_key,
            "chapter": chapter,
            "chapter_file": str(chapter_file),
            "book_title": book_title,
            "style_author": author["slug"],
            "style_author_display": author["display"],
            "persona_established": bool(persona.get("established")),
            "prompt_file": str(prompt_path),
            "created_at": dt.datetime.now().isoformat(),
            "status": "pending",
        }
        task_path = four_dir / f"{role_key}_task.json"
        save_json(task_path, task)
        tasks.append(task)

    manifest = {
        "chapter": chapter,
        "book_title": book_title,
        "style_author": author["slug"],
        "style_author_display": author["display"],
        "persona_established": bool(persona.get("established")),
        "persona_path": persona.get("path"),
        "persona_missing": persona.get("missing", []),
        "four_official_dir": str(four_dir),
        "tasks": [
            {"role": t["role"], "role_key": t["role_key"], "prompt_file": t["prompt_file"]}
            for t in tasks
        ],
        "generated_at": dt.datetime.now().isoformat(),
    }
    save_json(four_dir / "four_official_manifest.json", manifest)

    # 人格层未建立时，额外写一份醒目提醒产物（与 style_fewshot 的提醒并列）
    if not persona.get("established"):
        rem_path = four_dir / "persona_setup_reminder.md"
        write_text(
            rem_path,
            "# ⚠️ 人格层尚未建立\n\n"
            f"待填字段：{', '.join(persona.get('missing', []))}\n\n"
            f"请编辑：{persona.get('path')}\n\n"
            "（系统只提醒、不代填，以免 AI 把被模仿作者的角色口头禅套到你的主角身上。）\n",
        )

    return {
        "ok": True,
        "command": "generate",
        "chapter": chapter,
        "four_official_dir": str(four_dir),
        "manifest_file": str(four_dir / "four_official_manifest.json"),
        "task_count": len(tasks),
        "tasks": [t["prompt_file"] for t in tasks],
        "persona_established": bool(persona.get("established")),
        "persona_missing": persona.get("missing", []),
        "style_author": author["slug"],
        "style_author_display": author["display"],
        "message": (
            f"四官审计任务已生成（第 {chapter} 章，共 {len(tasks)} 份）。"
            f"{'⚠️ 人格层未建立，文风官将标记叙事人格漂移为无法判定。' if not persona.get('established') else ''}"
            "主 Agent 请读取 four_official_manifest.json 并派发四官审计。"
        ),
    }


def cmd_record(args: argparse.Namespace) -> Dict[str, Any]:
    project_root = Path(args.project_root).expanduser().resolve()
    chapter_file = Path(args.chapter_file)
    if not chapter_file.is_absolute():
        chapter_file = project_root / chapter_file
    gate_dir = project_root / "04_editing" / "gate_artifacts" / slugify(chapter_file.stem)
    four_dir = gate_dir / "four_official"
    ensure_dir(four_dir)

    result = {
        "chapter": args.chapter,
        "verdict": args.verdict,
        "p0_issues": [s.strip() for s in (args.p0 or "").split("|") if s.strip()],
        "p1_issues": [s.strip() for s in (args.p1 or "").split("|") if s.strip()],
        "p2_issues": [s.strip() for s in (args.p2 or "").split("|") if s.strip()],
        "scores": [s.strip() for s in (args.scores or "").split(",") if s.strip()],
        "summary": args.summary or "",
        "recorded_at": dt.datetime.now().isoformat(),
    }
    save_json(four_dir / "audit_result.json", result)

    report = (
        f"# 四官审计报告 · 第{args.chapter}章\n\n"
        f"综合评级：**{args.verdict}**\n\n"
        f"## 四官评分\n{chr(10).join('- ' + s for s in result['scores']) or '-（未记录）'}\n\n"
        f"## P0（必改）\n"
        + ("\n".join(f"- {x}" for x in result["p0_issues"]) or "- 无")
        + f"\n\n## P1（建议改）\n"
        + ("\n".join(f"- {x}" for x in result["p1_issues"]) or "- 无")
        + f"\n\n## P2（可选）\n"
        + ("\n".join(f"- {x}" for x in result["p2_issues"]) or "- 无")
        + f"\n\n## 主 Agent 汇总\n{result['summary'] or '（无）'}\n"
    )
    write_text(four_dir / "audit_report.md", report)

    return {
        "ok": True,
        "command": "record",
        "chapter": args.chapter,
        "verdict": args.verdict,
        "report_file": str(four_dir / "audit_report.md"),
        "result_file": str(four_dir / "audit_result.json"),
        "p0_count": len(result["p0_issues"]),
        "p1_count": len(result["p1_issues"]),
        "p2_count": len(result["p2_issues"]),
    }


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="多 Agent 四官审计任务生成器")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="生成四官审计任务（门禁通过后调用）")
    g.add_argument("--project-root", required=True)
    g.add_argument("--chapter", type=int, default=0, help="章节号；缺省则从文件名推断")
    g.add_argument("--chapter-file", required=True, help="章节文件路径")
    g.add_argument("--book-title", default="", help="书名（可选覆盖）")
    g.add_argument("--style-author", default="", help="风格作者 slug（可选覆盖）")

    r = sub.add_parser("record", help="记录四官审计结果")
    r.add_argument("--project-root", required=True)
    r.add_argument("--chapter", type=int, required=True)
    r.add_argument("--chapter-file", required=True)
    r.add_argument("--verdict", required=True, help="A+ / A / A- / B / B- / C")
    r.add_argument("--p0", default="", help="P0 问题，用 | 分隔")
    r.add_argument("--p1", default="", help="P1 问题，用 | 分隔")
    r.add_argument("--p2", default="", help="P2 问题，用 | 分隔")
    r.add_argument("--scores", default="", help="四官评分，用逗号分隔，如 文风官:90,结构官:88")
    r.add_argument("--summary", default="", help="主 Agent 汇总文本")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    dispatch = {"generate": cmd_generate, "record": cmd_record}
    handler = dispatch.get(args.cmd)
    if handler is None:
        payload: Dict[str, Any] = {"ok": False, "error": f"unknown_command:{args.cmd}"}
    else:
        try:
            payload = handler(args)
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "command": args.cmd, "error": repr(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
