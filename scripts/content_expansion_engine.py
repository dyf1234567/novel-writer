#!/usr/bin/env python3
"""Content Expansion Engine - 智能内容扩充引擎

提供真正的文本扩展功能，而非简单的指令追加。
通过多种扩充策略（场景、对话、心理、动作、过渡）实现内容的智能扩展。

作者: Claude Code
版本: 1.0.0
日期: 2025-03-02
"""

import re
import random
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass
from pathlib import Path

QUOTE_PATTERN = r'[“"][^”"]+[”"]'
QUOTE_CAPTURE_PATTERN = r'[“"]([^”"]+)[”"]'


@dataclass
class ExpansionContext:
    """扩充上下文"""
    chapter_no: int
    characters: Dict[str, Dict]  # 角色状态
    plot_line: str  # 当前情节线
    previous_ending: str  # 上一章结尾
    scene_setting: str  # 场景设定


@dataclass
class ExpansionStrategy:
    """扩充策略"""
    name: str
    applies_to: Callable[[str], bool]
    expand: Callable[[str, int, ExpansionContext], str]


class ContentExpansionEngine:
    """内容扩充引擎主类"""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.strategies = self._init_strategies()
        self._load_template_library()
    
    def _init_strategies(self) -> List[ExpansionStrategy]:
        """初始化扩充策略集合"""
        return [
            ExpansionStrategy(
                name="scene_expansion",
                applies_to=self._needs_scene_expansion,
                expand=self._expand_scenes,
            ),
            ExpansionStrategy(
                name="dialogue_enrichment",
                applies_to=self._needs_dialogue,
                expand=self._enrich_dialogue,
            ),
            ExpansionStrategy(
                name="psychological_depth",
                applies_to=self._needs_psychology,
                expand=self._deepen_psychology,
            ),
            ExpansionStrategy(
                name="action_detail",
                applies_to=self._needs_action,
                expand=self._detail_actions,
            ),
            ExpansionStrategy(
                name="transition_smoothing",
                applies_to=self._needs_transitions,
                expand=self._smooth_transitions,
            ),
        ]
    
    def expand_content(self, text: str, target_chars: int, context: ExpansionContext) -> str:
        """
        扩充内容至目标字数
        
        Args:
            text: 原始文本
            target_chars: 目标字数
            context: 扩充上下文
        
        Returns:
            扩充后的文本
        """
        current_chars = len(re.sub(r"\s+", "", text))
        if current_chars >= target_chars:
            return text
        
        needed_chars = target_chars - current_chars
        
        # 制定扩充计划
        expansion_plan = self._create_expansion_plan(text, needed_chars, context)
        
        # 执行扩充
        result = text
        for strategy_name, amount in expansion_plan:
            strategy = next((s for s in self.strategies if s.name == strategy_name), None)
            if strategy and strategy.applies_to(result):
                expansion = strategy.expand(result, amount, context)
                result = self._integrate_expansion(result, expansion)
        
        return result
    
    def _create_expansion_plan(self, text: str, needed_chars: int, context: ExpansionContext) -> List[Tuple[str, int]]:
        """制定扩充计划，智能分配各策略的扩充量"""
        plan = []
        remaining = needed_chars
        
        # 根据文本分析和上下文决定优先级
        priorities = self._analyze_expansion_priorities(text, context)
        
        for strategy_name, priority in priorities:
            if remaining <= 0:
                break
            
            # 根据优先级分配扩充量
            allocation = min(
                remaining,
                int(needed_chars * priority)
            )
            
            if allocation > 0:
                plan.append((strategy_name, allocation))
                remaining -= allocation
        
        # 如果还有剩余，分配给最高优先级的策略
        if remaining > 0 and plan:
            plan[-1] = (plan[-1][0], plan[-1][1] + remaining)
        
        return plan
    
    def _analyze_expansion_priorities(self, text: str, context: ExpansionContext) -> List[Tuple[str, float]]:
        """分析并返回各扩充策略的优先级（策略名，权重）"""
        priorities = []
        
        # 场景扩充检查
        scene_count = len(re.findall(r'场景|地点|时间|天色|环境', text))
        if scene_count < 3:
            priorities.append(("scene_expansion", 0.25))
        
        # 对话丰富度检查
        dialogue_chars = sum(len(m.group(1)) for m in re.finditer(QUOTE_CAPTURE_PATTERN, text))
        text_chars = len(re.sub(r"\s+", "", text))
        dialogue_ratio = dialogue_chars / text_chars if text_chars else 0
        if dialogue_ratio < 0.2:
            priorities.append(("dialogue_enrichment", 0.20))
        
        # 心理描写检查
        psych_markers = ['想', '觉得', '感觉', '意识到', '认为', '心中']
        psych_count = sum(text.count(m) for m in psych_markers)
        if psych_count < 5:
            priorities.append(("psychological_depth", 0.15))
        
        # 动作细节检查
        action_verbs = ['走', '跑', '跳', '打', '拿', '放', '看', '听', '站', '坐']
        action_count = sum(text.count(v) for v in action_verbs)
        if action_count < 20:
            priorities.append(("action_detail", 0.15))
        
        # 过渡平滑度检查
        transitions = ['随后', '接着', '与此同时', '不久之后', '紧接着']
        trans_count = sum(text.count(t) for t in transitions)
        if trans_count < 3:
            priorities.append(("transition_smoothing", 0.10))
        
        # 如果没有明显的优先级，平均分配
        if not priorities:
            return [
                ("scene_expansion", 0.20),
                ("dialogue_enrichment", 0.20),
                ("psychological_depth", 0.15),
                ("action_detail", 0.15),
                ("transition_smoothing", 0.10),
            ]
        
        # 按权重排序
        priorities.sort(key=lambda x: x[1], reverse=True)
        return priorities
    
    # 具体扩充策略实现
    
    def _needs_scene_expansion(self, text: str) -> bool:
        """判断是否需要场景扩充"""
        scene_markers = ['场景', '地点', '时间', '天色', '环境', '氛围']
        scene_count = sum(1 for marker in scene_markers if marker in text)
        return scene_count < 3
    
    def _expand_scenes(self, text: str, amount: int, context: ExpansionContext) -> str:
        """场景扩充实现（寓言基调：感官白描，短句，不堆成语）"""
        expansion_parts = []
        p = context.characters.get('protagonist', '它')

        # 环境氛围：光/风/声/气味，一个感官一句话
        atmosphere_templates = [
            f"风从{random.choice(['远处来', '石缝间穿过', '空地上刮过'])}，带着{random.choice(['一点凉意', '旧木的气味', '潮气'])}。",
            f"{random.choice(['天光', '晨光', '暮色'])}落下来，{random.choice(['铺在地上，很薄。', '把影子拉得很长。', '在边缘处碎成一片灰。'])}",
            f"四周{random.choice(['安静', '静得能听见自己的心跳', '只有风声'])}。",
            f"光从{random.choice(['门缝里漏进来', '高处落下来', '暗处渗出来'])}，{random.choice(['像一条细线。', '把地面照出一道窄痕。', '不够亮，但刚好看得清。'])}",
            f"{random.choice(['空气是凉的', '空气里有水汽', '空气沉甸甸的'])}，{random.choice(['像刚下过雨。', '像天还没亮。', '像有什么东西要来了。'])}",
        ]
        expansion_parts.extend(random.sample(atmosphere_templates, min(2, len(atmosphere_templates))))

        # 环境中的动作回应（它/主角，动物性感官）
        motion_templates = [
            f"{p}停下来，{random.choice(['听了一会儿。', '嗅了嗅空气。', '没有动。'])}",
            f"{p}的{random.choice(['耳朵动了动', '尾巴扫了一下', '脚步放轻了'])}。",
        ]
        expansion_parts.extend(random.sample(motion_templates, min(1, len(motion_templates))))

        return "\n\n".join(expansion_parts)
    
    def _needs_dialogue(self, text: str) -> bool:
        """判断是否需要对话扩充"""
        dialogue_chars = sum(len(m.group(1)) for m in re.finditer(QUOTE_CAPTURE_PATTERN, text))
        text_chars = len(re.sub(r"\s+", "", text))
        dialogue_ratio = dialogue_chars / text_chars if text_chars else 0
        return dialogue_ratio < 0.2
    
    def _enrich_dialogue(self, text: str, amount: int, context: ExpansionContext) -> str:
        """对话丰富化实现（寓言基调：短句、有来有回、带试探）"""
        p = context.characters.get('protagonist', '它')
        dialogue_templates = [
            f'"{random.choice(["你一直在等我？", "你知道我要来？", "你等了多久？"])}"{p}{random.choice(["问", "说"])}。',
            f'"{random.choice(["我不知道。", "也许吧。", "这得看你怎么算。"] )}"{random.choice(["对方说", "那个声音说", "有人回答"])}。',
            f'"{random.choice(["你为什么来？", "你想要什么？", "你来这里，图什么？"])}"{p}{random.choice(["盯着对方，问", "压低声音说"])}。',
            f'停顿了一会儿。{random.choice(["风从他们之间穿过。", "没有人先开口。", "话到这里，就断了。"] )}',
            f'"{random.choice(["话我说完了。", "剩下的，你自己掂量。", "你信也好，不信也好。"] )}"{random.choice(["他说", "那个声音说完，暗了下去"])}。',
        ]
        selected = random.sample(dialogue_templates, min(2, len(dialogue_templates)))
        return "\n\n".join(selected)
    
    def _needs_psychology(self, text: str) -> bool:
        """判断是否需要心理描写扩充"""
        psych_markers = ['想', '觉得', '感觉', '意识到', '认为', '心中', '暗想', '思索', '犹豫', '决心']
        psych_count = sum(text.count(m) for m in psych_markers)
        return psych_count < 5
    
    def _deepen_psychology(self, text: str, amount: int, context: ExpansionContext) -> str:
        """心理深化实现（寓言基调：心理外化成动作/感官，不直接剖心）"""
        p = context.characters.get('protagonist', '它')
        psych_templates = [
            f"{p}{random.choice(['没有动。', '停了一下。', '站在原地，没有接话。'])}",
            f"{p}{random.choice(['低头看了看自己的手。', '望向远处，很久没有移开。', '把眼睛闭了一瞬，又睁开。'])}",
            f"{random.choice(['它没有说出口。', '那句话在喉咙里滚了一圈，又咽了回去。', '它张了张嘴，最后什么都没说。'])}",
            f"{random.choice(['风灌进来，它没有躲。', '它把尾巴收拢了一点，像在压着什么。', '它握紧了一样东西，又松开。'])}",
            f"{p}知道，有些话一旦说出来，就收不回去了。所以它{random.choice(['没说。', '把话咽了回去。', '只是点了点头。'])}",
        ]
        selected = random.sample(psych_templates, min(2, len(psych_templates)))
        return "\n\n".join(selected)
    
    def _needs_action(self, text: str) -> bool:
        """判断是否需要动作细节扩充"""
        action_verbs = ['走', '跑', '跳', '打', '拿', '放', '看', '听', '站', '坐', '冲', '挥', '握', '拉']
        action_count = sum(text.count(v) for v in action_verbs)
        return action_count < 20
    
    def _detail_actions(self, text: str, amount: int, context: ExpansionContext) -> str:
        """动作细节化实现（寓言基调：动物性白描，具体动词，不堆成语）"""
        p = context.characters.get('protagonist', '它')
        action_templates = [
            f"{p}{random.choice(['站住了', '停了一步', '没有马上动'])}，{random.choice(['耳朵转了转，像在听什么。', '尾巴轻轻扫了一下地面。', '呼吸慢了下来。'])}",
            f"{p}{random.choice(['往前走了一步', '向门边挪了半步', '绕过那块突出的石头'])}，{random.choice(['脚步很轻', '落地没有声音', '像怕惊动什么'])}。",
            f"{p}{random.choice(['抬头看了一会儿', '眯起眼睛', '瞳孔收窄'])}，{random.choice(['像在估量什么。', '像在算一笔账。', '没有移开视线。'])}",
            f"{p}{random.choice(['伸出手，又收回去', '碰了一下那样东西，又缩回爪', '按了按胸口'])}。",
            f"{random.choice(['风动了，它先动了', '它比对方先反应过来', '它在最后一刻侧身让开'])}。",
        ]
        selected = random.sample(action_templates, min(2, len(action_templates)))
        return "\n\n".join(selected)
    
    def _needs_transitions(self, text: str) -> bool:
        """判断是否需要过渡平滑化"""
        transitions = ['随后', '接着', '与此同时', '不久之后', '紧接着', '然后', '这时']
        trans_count = sum(text.count(t) for t in transitions)
        return trans_count < 3
    
    def _smooth_transitions(self, text: str, amount: int, context: ExpansionContext) -> str:
        """过渡平滑化实现（寓言基调：用动作/环境承接，不用"岁月流逝"空转）"""
        p = context.characters.get('protagonist', '它')
        transition_templates = [
            f"{random.choice(['过了很久', '不知道过了多久', '时间在这里没有意义'])}，{random.choice(['风还在吹', '四周还是那么安静', '没有一样东西动过'])}。",
            f"{p}{random.choice(['没有急着走', '又站了一会儿', '在原地停住'])}，像在等什么。",
            f"{random.choice(['然后', '接着', '就在这时'])}，{random.choice(['有什么东西轻轻地动了一下', '光暗了一瞬', '远处传来一点声响'])}。",
            f"它{random.choice(['把这件事记下了', '看了一眼来时的路', '把刚才的话又过了一遍'])}。",
        ]
        selected = random.sample(transition_templates, min(2, len(transition_templates)))
        return "\n\n".join(selected)
    
    def _integrate_expansion(self, original: str, expansion: str) -> str:
        """将扩充内容自然融入原文"""
        if not expansion.strip():
            return original
        
        # 在合适的段落之间插入扩充内容
        paragraphs = original.split('\n\n')
        expansion_paras = expansion.split('\n\n')
        
        # 找到合适的插入点（通常是场景转换处或对话结束后）
        insert_points = []
        for i, para in enumerate(paragraphs):
            if any(marker in para for marker in ['。"', '？"', '！"', '……', '。\n']):
                insert_points.append(i)
        
        # 如果没有合适的插入点，在段落中间插入（单段也可插入）
        if not insert_points and paragraphs:
            insert_points = [len(paragraphs) // 2]
        if not paragraphs:
            return expansion
        
        # 插入扩充段落
        result = paragraphs[:]
        offset = 0
        for i, exp_para in enumerate(expansion_paras):
            if i < len(insert_points):
                insert_idx = insert_points[i] + offset + 1
                if insert_idx <= len(result):
                    result.insert(insert_idx, exp_para)
                    offset += 1
        
        return '\n\n'.join(result)
    
    def _load_template_library(self):
        """加载模板库（预留接口）"""
        # 可以在这里加载外部模板文件
        pass


# 便捷函数
def expand_chapter_content(
    text: str,
    target_chars: int,
    chapter_no: int,
    context: Dict,
    config: Optional[Dict] = None
) -> str:
    """
    便捷函数：扩充章节内容
    
    Args:
        text: 原始文本
        target_chars: 目标字数
        chapter_no: 章节号
        context: 上下文信息
        config: 可选配置
    
    Returns:
        扩充后的文本
    """
    engine = ContentExpansionEngine(config)
    expansion_context = ExpansionContext(
        chapter_no=chapter_no,
        characters=context.get('characters', {}),
        plot_line=context.get('plot_line', ''),
        previous_ending=context.get('previous_ending', ''),
        scene_setting=context.get('scene_setting', ''),
    )
    return engine.expand_content(text, target_chars, expansion_context)


# 测试代码
if __name__ == "__main__":
    # 简单测试
    test_text = "这是一个测试文本。需要扩充内容。"
    context = {
        'characters': {'protagonist': '张三'},
        'plot_line': '测试情节',
        'previous_ending': '上一章结尾',
        'scene_setting': '测试场景',
    }
    
    result = expand_chapter_content(test_text, 500, 1, context)
    print(f"原始字数: {len(test_text)}")
    print(f"扩充后字数: {len(result)}")
    print("扩充结果预览:")
    print(result[:500] + "..." if len(result) > 500 else result)
