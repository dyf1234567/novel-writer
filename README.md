# novel-writer

面向 Codex 的中文长篇小说创作 skill。它以文件化长期记忆维护人物、时间线、世界设定、伏笔与章节摘要，并提供章纲、场景节拍、节奏追踪、计划偏差检查、检索辅助和阶段审计脚本。

## 安装

将本仓库克隆或复制到 Codex skills 目录，使目录结构为：

```text
~/.codex/skills/novel-writer/SKILL.md
```

重启或刷新 Codex 后，可用 `$novel-writer` 显式调用，也可让 Codex 在长篇小说任务中自动选择它。

## 使用示例

```text
$novel-writer 继续写当前小说下一章，并保持人物、时间线和伏笔一致。
```

项目正文、向量索引、作者语料和本地配置不应提交到本仓库。可选的本地 embedding/RAG 能力需要使用者自行配置；skill 本体仍可在未安装 embedding 服务时使用文件检索与账本工作流。

## 旧项目升级

新版检索索引要求逐章接受记录。原稿不会被自动收编；请先审阅，再按 [项目策略与迁移说明](references/project-policy.md) 执行 `canonical_state.py accept` 和索引重建。节奏配额、强制断章等规则改为项目显式启用；可选的构思方法见 [创作工具](references/creative-toolkit.md)。

`continue-write` 默认只报告字数、对话比例、重复度等机械指标，不用它们单独拦稿；确需数值硬门槛时添加 `--strict-prose-metrics`。Beat Sheet、广泛调研、批量审稿任务和四官审稿任务需主动开启。人工创作检查点及卷末审计要求仍默认开启；审稿任务文件不代表 Agent 已完成审稿。

宿主默认按以下节奏实际审阅：每章针对性连续性检查；每 10 章创作检查点与文风复核；卷末全卷审计与多 Agent 审稿；重大剧情接受前红队审查。具体执行要求见 [审查节奏](references/quality-gates.md)。这些语义审阅由宿主完成；缺少多 Agent 工具时逐项审阅并说明执行方式。

人物设计和关键关系场景可按需使用 [人物张力指南与卡片](references/character-tension.md)，检查目标、选择和后果。日常场景不强制填卡，也不要求所有人物都有创伤、面具或悲剧结局；填写后的卡片保存在小说项目中。
