#!/usr/bin/env python3
"""text_humanizer 检测核心测试

锚定 8.1.0 修复引入的行为契约：
1. 顶层兼容字段（ai_score / vocab_hits / weak_adverb_density /
   para_summary_hits / dialogue_monotone）必须存在；
2. ai_score 量纲：low 档 <=25 < medium 档，与 novel_chapter_writer
   的 ">25 触发自动润色" 及 executor 的 "severity >= medium" 语义一致；
3. Category 8 对话同质化检测的三种判定。

运行方式:
    python scripts/tests/test_text_humanizer.py
"""

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from text_humanizer import detect_patterns  # noqa: E402


CLEAN_TEXT = (
    "他把信折好，放进锁匣。门外传来马蹄声。"
    "他吹灭灯，从后窗翻了出去。马蹄声在巷口停了。"
    "他贴着墙走了半条街，才想起来锁匣没有锁。"
)

# 恰好 1 类问题（AI 高频词），无弱化副词 → low 档
ONE_ISSUE_TEXT = (
    "他推门进去，屋里没人。桌上的茶凉透了。"
    "他不禁皱眉，把窗户关上。雨声小了一些。"
    "他坐下来等，等到蜡烛烧掉一半。"
)

# 2 类问题（AI 高频词 + 弱化副词密度）→ medium 档
MEDIUM_TEXT = (
    "他不禁感到一阵心悸。她微微点头，缓缓转身，轻轻叹了口气。"
    "他仿佛看见什么，却没有说。她淡淡地笑了笑，走到窗边。"
    "他默默站着，隐隐觉得不安。"
)

# 5 类问题 → high 档（此前手工验证过 severity=high / ai_score=85）
HIGH_TEXT = (
    "他不禁感到一阵心悸。仿佛一切都映入眼帘。此时此刻，他心中暗道不妙。"
    "她嘴角微扬。他微微点了点头，淡淡地说道，这次会面意义深远，未来可期。"
    "不难看出，他已下定决心。与此同时，他缓缓转身，不由自主地叹了口气。"
)


class TestCompatFields(unittest.TestCase):
    """顶层兼容字段契约：writer 自动润色分支依赖这些键存在。"""

    def test_top_level_compat_fields_present(self):
        for text in (CLEAN_TEXT, MEDIUM_TEXT, HIGH_TEXT):
            d = detect_patterns(text)
            for key in (
                "ai_score",
                "vocab_hits",
                "weak_adverb_density",
                "para_summary_hits",
                "dialogue_monotone",
                "severity",
                "issues",
                "details",
            ):
                self.assertIn(key, d, f"缺少顶层字段 {key}")

    def test_vocab_hits_match_details(self):
        d = detect_patterns(HIGH_TEXT)
        self.assertGreater(len(d["vocab_hits"]), 0)
        phrases = {h["phrase"] for h in d["vocab_hits"]}
        detail_phrases = {
            h["phrase"] for h in d["details"]["ai_vocab"]["hits"]
        }
        self.assertEqual(phrases, detail_phrases)


class TestAiScoreContract(unittest.TestCase):
    """ai_score 量纲契约，防止未来调整权重时悄悄改变门禁触发行为。"""

    def test_low_severity_score_not_over_threshold(self):
        for text in (CLEAN_TEXT, ONE_ISSUE_TEXT):
            d = detect_patterns(text)
            self.assertEqual(d["severity"], "low", text[:20])
            self.assertLessEqual(
                d["ai_score"], 25,
                f"low 档分数越界: {d['ai_score']}（issue_count={d['issue_count']}）",
            )

    def test_medium_severity_score_over_threshold(self):
        d = detect_patterns(MEDIUM_TEXT)
        self.assertIn(d["severity"], ("medium", "high"))
        self.assertGreater(d["ai_score"], 25)

    def test_high_severity_score_band(self):
        d = detect_patterns(HIGH_TEXT)
        self.assertEqual(d["severity"], "high")
        self.assertGreaterEqual(d["ai_score"], 60)

    def test_writer_trigger_equivalence(self):
        """>25 触发条件必须与 severity >= medium 等价（writer/executor 双入口一致）。"""
        for text in (CLEAN_TEXT, ONE_ISSUE_TEXT, MEDIUM_TEXT, HIGH_TEXT):
            d = detect_patterns(text)
            triggered_by_score = float(d.get("ai_score", 0)) > 25
            triggered_by_severity = d["severity"] in ("medium", "high")
            self.assertEqual(
                triggered_by_score, triggered_by_severity,
                f"量纲与 severity 不一致: score={d['ai_score']} severity={d['severity']}",
            )


class TestDialogueMonotone(unittest.TestCase):
    """Category 8 对话同质化（词法代理信号）。"""

    MONOTONE = (
        "他微微点头。“今天天气不错。”他说道。“是啊。”她说道。"
        "“我们出发吧。”他说道。“去哪里？”她问道。"
        "“山那边。”他说道。“为什么？”她问道。"
    )

    DIVERSE = (
        "他推门进来。“今天天气不错。”他说道。她笑道：“是啊。”"
        "“我们出发吧。”他问道。她叹道：“这么急？”"
        "“山那边。”他喊道。她答道：“好吧。”"
    )

    FEW_QUOTES = "“走。”他说道。“去哪。”她问道。“外面。”他说道。"

    def test_monotone_detected(self):
        d = detect_patterns(self.MONOTONE)
        self.assertTrue(d["dialogue_monotone"])
        info = d["details"]["dialogue_variety"]
        self.assertGreaterEqual(info["quote_count"], 6)
        self.assertLessEqual(len(info["tag_kinds"]), 2)

    def test_diverse_tags_not_flagged(self):
        d = detect_patterns(self.DIVERSE)
        self.assertFalse(d["dialogue_monotone"])

    def test_too_few_quotes_not_flagged(self):
        d = detect_patterns(self.FEW_QUOTES)
        self.assertFalse(d["dialogue_monotone"])


if __name__ == "__main__":
    unittest.main()
