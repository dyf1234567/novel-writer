#!/usr/bin/env python3
"""集中配置管理模块

管理所有硬编码的配置值，支持百万字级别小说的创作流程。
所有配置可通过环境变量覆盖。
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional


@dataclass
class RetrievalConfig:
    """RAG检索配置"""
    
    # 停用词表
    stopwords: Set[str] = field(default_factory=lambda: {
        "我们", "你们", "他们", "她们", "它们", "这个", "那个", "一种", "已经", "因为", "所以", "如果",
        "但是", "然后", "自己", "不是", "不会", "就是", "还是", "一个", "一些", "可以", "时候", "什么",
        "怎么", "这样", "那样", "起来", "进去", "出来", "一下", "一样", "以及", "并且", "或者", "然后",
        "这里", "那里", "这些", "那些", "这样", "那样", "如此", "非常", "十分", "相当", "真的",
    })
    
    # 检索触发关键词
    trigger_keywords: Set[str] = field(default_factory=lambda: {
        "冲突", "反转", "伏笔", "回收", "真相", "背叛", "联盟", "新角色", "时间线", "回忆",
        "穿越", "死亡", "复活", "势力", "升级", "突破", "决战", "危机", "转折", "悬念",
        "揭露", "身份", "秘密", "阴谋", "复仇", "救赎", "牺牲", "传承", "觉醒", "封印",
    })
    
    # 轻场景关键词（用于跳过检索）
    light_scene_keywords: Set[str] = field(default_factory=lambda: {
        "日常", "过渡", "环境描写", "吃饭", "赶路", "休整", "闲聊", "铺垫",
        "修炼", "冥想", "休息", "准备", "整理", "收拾", "散步", "观光",
    })
    
    # 检索参数
    candidate_k: int = 12  # 粗筛候选数
    top_k: int = 4  # 精排返回数
    passage_max_chars: int = 220  # 片段最大字符数
    passages_per_chapter: int = 2  # 每章提取片段数
    
    # 缓存配置
    cache_max_entries: int = 200
    cache_ttl_seconds: int = 3600  # 1小时过期
    
    @classmethod
    def from_env(cls) -> "RetrievalConfig":
        """从环境变量加载配置"""
        config = cls()
        
        if "RETRIEVAL_CANDIDATE_K" in os.environ:
            config.candidate_k = int(os.environ["RETRIEVAL_CANDIDATE_K"])
        
        if "RETRIEVAL_TOP_K" in os.environ:
            config.top_k = int(os.environ["RETRIEVAL_TOP_K"])
        
        if "RETRIEVAL_CACHE_TTL" in os.environ:
            config.cache_ttl_seconds = int(os.environ["RETRIEVAL_CACHE_TTL"])
        
        return config


# =============================================================================
# 全局配置实例
# =============================================================================

# 懒加载的单例模式
_retrieval_config: Optional[RetrievalConfig] = None


def get_retrieval_config() -> RetrievalConfig:
    """获取检索配置（懒加载）"""
    global _retrieval_config
    if _retrieval_config is None:
        _retrieval_config = RetrievalConfig.from_env()
    return _retrieval_config


# =============================================================================
# 版本信息
# =============================================================================

__version__ = "9.0.0"
# novel-writer 9.0.0 变更（合并版：oh-story 工艺层 + nw 检索层）：
# - 写作工艺层整体引入 oh-story-claudecode（MIT，见 THIRD_PARTY_NOTICE.md）：
#   细纲九字段/追踪事务/章流程/检测三件套/55 份方法论文档
# - plot_rag_retriever 与 canonical_state 适配 oh 目录结构
#   （NOVEL_MANUSCRIPT_DIR=正文），新增 --no-skip 强制检索开关
# - SKILL.md 重写为融合流程（铁律五条 + 检索桥 + style-writer 桥）
# novel-writer 8.2.0 变更（结构句式检测层）：
# - text_humanizer 移植 oh-story check-ai-patterns 的 blocking 层（MIT）：
#   not-is-comparison / negation-parade / voice-contrast / trailer-ending / em-dash
#   五类结构句式，含引号内台词掩码与 either-or/反问尾巴误报排除；
#   命中即 severity>=medium、ai_score +30/处（>25 阈值语义不变），
#   ai_flavor_gate 与 writer 自动润色自动生效
# - 双 skill 对比实验（10 章×2 实测）校准：移植后 nw 检测器与上游
#   检测结论完全一致（原词法层对 20 章产出零区分度）
# novel-writer 8.1.1 变更（审计修复轮）：
# - 修复 continue_write 中 result 提前使用导致的 UnboundLocalError，
#   人格层提醒（persona_setup 警告）恢复进入输出 JSON
# - improve_text_minimally 改为 no-op：不再把指令文本与完整拼装上下文
#   粘进章节正文；无 LLM 时记录警告并停止空转
# - check_publish_ready 失败标记优先：修复「不通过」被成功词「通过」
#   子串误判、检查恒真的问题
# - 删除从未工作的 MCP Codex 免密钥路径（write_json 未定义即 NameError）
# - 死件清理：auto_novel_writer.py、content_expansion_engine.py、
#   --max-chapter-variance、QualityConfig / FlowConfig
# 8.1.0 变更：
# - text_humanizer 顶层兼容字段 + Category 8 对话同质化检测（修复 writer
#   自动去AI味润色死代码）；ai_flavor_gate 每章铁律；CLI --version；
#   可移植 Python 解释器解析（修复 Windows 测试）
PROG_NAME = "novel-writer"
__all__ = [
    "RetrievalConfig",
    "get_retrieval_config",
    "PROG_NAME",
]
