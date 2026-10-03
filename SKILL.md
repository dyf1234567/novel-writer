---
name: novel-writer
description: 管理已建立或新建的中文长篇小说项目。当任务涉及持久化章节状态、连续性检索、大纲感知的草稿撰写、修订或发布检查时使用。适用于多章节长篇与连载小说；单篇短文、一次性文段改写、或单独的作者风格提取不要激活本技能。
---

# Novel Writer（长篇小说写作技能）

在不把某一种写作配方当作普遍真理的前提下协调长篇小说创作。保留用户的创作决定权，同时保证项目状态可恢复、内部自洽。

## 请求路由

加载详细指引前，先选定一个主模式：

- **创建或规划项目**：读 [workflows.md](references/workflows.md) 的「Create」「Plan」小节。
- **探索剧情备选方案、开篇策略、人物主动性或节奏**：请求确实需要写作指导时，读 [creative-toolkit.md](references/creative-toolkit.md)。
- **设计重要人物、关键关系场景，或诊断动机薄弱**：读 [character-tension.md](references/character-tension.md)。其人物卡片按需选用；日常场景不要求填卡，创伤、面具或悲剧结局永远不是必需项。
- **撰写或续写章节**：读 [workflows.md](references/workflows.md) 的「Draft and continue」小节，外加 [project-contract.md](references/project-contract.md)。
- **修订已有章节或大纲**：读 [workflows.md](references/workflows.md) 的「Revise」小节。绝不自行推定获得重写未受影响章节的授权。
- **查看状态、连续性、人物、时间线或伏笔**：读 [project-contract.md](references/project-contract.md)。仅查看不构成编辑授权。
- **执行编辑或发布检查**：读 [quality-gates.md](references/quality-gates.md)。
- **运营长连载或百万字项目**：读 [long-form-operations.md](references/long-form-operations.md)，涉及混合检索、全卷审计与人工检查点。
- **接受旧章节、配置门禁、恢复审计**：读 [project-policy.md](references/project-policy.md)。
- **应用作者风格包**：读 [style-integration.md](references/style-integration.md)。除非用户明确要求改编或同人，保持原作设定关闭。

独立的短篇或单段文字，直接写，不初始化长篇项目机制——除非用户要求将其转为受管理的小说项目。

## 建立项目上下文

改动项目之前：

1. 从用户路径或当前工作区解析项目根目录。不得臆造项目位置。
2. 检查既有状态与配置。保留未知字段与用户手写的备注。
3. 判定请求是只读、起草、修订，还是状态迁移。
4. 使用满足请求的最小工作流。不因为项目支持调研、多 Agent 审稿、风格模仿或批量写作，就顺手运行它们。

新建项目时，只确认实质影响结果的选择：前提、目标篇幅、视角、自动化程度、不可协商的约束。用户不确定时主动给出默认值。

## 状态不变量

项目文件是持久状态；对话历史不是。

- 正文字本与计划、审阅笔记、提示词、工具输出保持分离。
- 不悄悄改动已确认的大纲锚点、人物事实、时间线事实或已回收伏笔。
- 记录变更了某个持久事实的章节或修订。
- 把生成式摘要当作可能出错的证据，而非不容置疑的真相。来源冲突时优先正文原文与用户确认的事实。
- 章节被接受后，更新相关项目记忆与检索索引。被用户否决的草稿、或被阻断检查判失败的草稿，不得进入规范记忆。
- 索引或使用历史段落前，先核验该章的内容绑定接受记录。旧项目需要显式收编；不因文件躺在正文书目录里就默默信任它。
- 大纲级联或多文件重写前，先保证可恢复性。

状态所有权与状态迁移的细节见 [project-contract.md](references/project-contract.md)。

## 撰写契约

只装配当前章节所需的上下文：

1. 当前大纲锚点与章节目标；
2. 近期章节摘要；
3. 相关人物、地点、时间线事实、活跃剧情线与伏笔；
4. 连续性风险值得时，检索历史段落；
5. 可选的风格上下文；
6. 用户显式约束。

生成干净的正文。绝不在正文区域内放置分析标签、TODO、角色说明或审阅评语。

**去AI味为每章强制铁律（⛔ 默认启用，不可选关闭）**：每章草稿完成后必须执行 AI 痕迹检测（`text_humanizer.py`），严重程度「中等」及以上必须完成两遍式人性化润色并复核后才可接受；检测未执行（severity=未知）同样阻断。`chapter_gate_check.py` 以阻断项 `ai_flavor_gate` 强制执行——门禁不通过时，唯一合法操作是完成润色或修复，不得跳过。

节奏配额与断章频率是项目显式启用的策略。`continue-write` CLI 默认把文字指标记录为建议信号；仅当用户要求数值阈值阻断接受时使用 `--strict-prose-metrics`。显式 Beat Sheet 模式可以强制其自身的 Beat 目标。不要把指标合格当作文学认可。

按 [quality-gates.md](references/quality-gates.md) 的默认节奏执行审阅：每章针对性连续性检查 + 去AI味铁律；每 10 个已接受章节创作检查点与风格复核；卷末全卷审计与多 Agent 审稿；重大不可逆剧情决策红队审查。这些语义审阅由宿主完成，并报告已完成、待处理或不可用；脚本本身不构成审阅完成。

## 质量分级

检查分三级严重度：

- **阻断（Blocking）**：正文污染、已确认事实矛盾、无效状态迁移、用户硬约束违反、预期产物不完整或结构无效、以及 AI 痕迹「中等/严重/未知」未闭环。发布或更新规范记忆前先停下。
- **降级（Degraded）**：检索不可用、非关键索引过期、可选分析器失败。仅在明确告警并记录兜底方案后继续。
- **节奏外可选（Optional）**：额外的风格审计与多 Agent 审稿、人工化附加轮次、仪表盘、广泛调研——除非项目配置提升了它们的级别。

不得声称任何工作流能在任意字数下保证一致性。报告哪些检查跑了、哪些跳过了、哪些仍不确定。详见 [quality-gates.md](references/quality-gates.md)。

## 脚本执行

脚本位于 `scripts/`。以可移植方式解析 Python：

1. 配置了 `NOVEL_WRITER_PYTHON` 时优先使用；
2. 否则使用环境中当前可用的 Python 解释器；
3. Windows 上，`py` 启动器是可接受的兜底。

绝不在生成的项目文件或指令中嵌入用户专属的绝对解释器路径。

主要入口：

```text
scripts/novel_flow_executor.py one-click
scripts/novel_flow_executor.py continue-write
scripts/novel_flow_executor.py revise-outline
scripts/plot_rag_retriever.py build|query
scripts/canonical_state.py status|accept
scripts/local_vector_retriever.py build|query
scripts/volume_audit.py collect|complete|status
scripts/creative_checkpoint.py status|approve|reject
scripts/chapter_gate_check.py
scripts/gate_repair_plan.py
scripts/story_graph_builder.py
scripts/style_audit.py
scripts/text_humanizer.py detect|report|prompt
```

构造参数尚未确立的命令前，先查看 `--help`（各 CLI 亦支持 `--version`）。确定性状态操作用脚本；文字、语义审阅与创作取舍用模型判断。

## 完成报告

对每次变更，报告：

- 正文或状态改了什么；
- 规范记忆与索引是否已更新；
- 跑过的阻断、降级、可选检查；
- 未解决的风险或待用户决策的事项。

不要把正则或 schema 校验通过等同于文学质量。
