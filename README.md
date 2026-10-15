# novel-writer

中文长篇小说全流程创作 skill（v9 合并版）。写作工艺层源自 [oh-story-claudecode](https://github.com/zenstory-ai/oh-story-claudecode)（MIT，见 [THIRD_PARTY_NOTICE.md](THIRD_PARTY_NOTICE.md)）；旧信息混合检索与内容绑定凭据为 novel-writer 原生。

```text
细纲九字段 → 写前组装 → 正文写作 → 章收口检测 → 追踪事务 → 检索建索引
```

## 架构（三层，各取所长）

| 层 | 来源 | 内容 |
|----|------|------|
| 写作工艺 | oh-story | 细纲九字段模板与验收、写前必读体系、writer prompt 槽位组装、章收口（标点 + 22 类 AI 句式检测 + 退化检测 + 字数，一键）、追踪事务账本（防呆校验 + 派生状态卡 + 双时间线）、55 份写作方法论文档 |
| 长程记忆 | novel-writer | FTS5/词法 + 本地向量混合检索（旧信息查找：几十章前的伏笔、物件、对白）；SHA256 内容绑定接受凭据（正文改动即失效，索引只收已接受章节） |
| 作者风格 | style-writer（独立 skill） | 风格基线写入书目录 `设定/文风.md`（自定义文风优先级最高）；写前 few-shot 经 writer prompt 文风槽注入 |

## 安装

克隆到你的编程 Agent 的 skills 目录（Codex 为例）：

```text
~/.codex/skills/novel-writer/SKILL.md
```

需要 Python 3（脚本零第三方依赖）与 Node.js 18+（章收口检测）；本地向量检索可选（Ollama + bge-m3）。

## 快速开始

```text
$novel-writer 帮我开书：都市悬疑，夜班出租车司机捡到一份死人名单
```

开书按确认点推进：定方向 → 定设定 → 卷纲 → 首批细纲（每章过 `check-outline-contract.js` 结构验收）→ 你说写正文才写。日常推进：

| 场景 | 说法 |
|------|------|
| 写下一章 | "日更" / "继续写" / "写第N章" |
| 补大纲 | "出细纲" / "补纲" / "规划下一卷" |
| 改稿 | "修改第X章" / "回炉" |
| 查旧事 | "烟头牌子哪章写的？"（走检索） |

## 每章闭环

1. **细纲门禁**：九字段齐备才开写（`check-outline-contract.js` 验收）
2. **写前组装**：`build_writer_prompt.py` 产出槽位式 prompt（状态速记、必读设定、文风槽）
3. **写作**：宿主或 narrative-writer 子代理按细纲落笔
4. **章收口**：`storyctl.py chapter check --fix-punctuation` 一键跑标点整理 + AI 句式检测 + 退化检测 + 字数；**blocking 同轮修净才算完成**
5. **追踪事务**：`tracking_commit.py` 提交章末 delta（角色快照、伏笔、时间线、下章承诺），账本校验防漂移
6. **检索索引**：`plot_rag_retriever.py build`（顺手，一条命令）

## 铁律（SKILL.md 摘要）

1. 无细纲不写正文
2. 写后 blocking 同轮清零（唯一豁免：章首标记 `<!-- 去味:跳过 -->`）
3. 追踪只走事务，禁手改派生视图
4. 不承诺一致性保证：如实报告跑了什么、跳了什么、什么不确定
5. 去味删改保护：轻≤15% / 中≤25% / 重≤35%，冲突标 `[需复核]` 不硬改

## 旧信息检索（novel-writer 原生）

```bash
NOVEL_MANUSCRIPT_DIR=正文 python scripts/plot_rag_retriever.py build --project-root <书目录> --engine fts5
NOVEL_MANUSCRIPT_DIR=正文 python scripts/plot_rag_retriever.py query --project-root <书目录> \
  --engine fts5 --query "<旧信息关键词>" --no-skip
```

检索结果是证据不是结论：命中片段回读原文确认后再引用。内容绑定凭据：`canonical_state.py accept` 按正文 SHA256 绑定，防篡改；存量项目先逐章 accept 再建索引。

## style-writer 风格桥

作者风格包（独立 skill [style-writer](https://github.com/dyf1234567/style-writer)）经两个集成点接入，不改动本流程：风格基线写 `设定/文风.md`；写前 few-shot 填 writer prompt 文风槽。原作设定默认关闭，细则见 [references/style-integration.md](references/style-integration.md)。

## 书项目目录（oh 结构）

```text
{书名}/
├── 设定/（世界观、角色、势力、关系、题材定位、文风.md）
├── 大纲/（大纲、卷纲_第X卷、排纲底稿、细纲_第NNN章）
├── 正文/（第NNN章_章名.md）
├── 追踪/（_tracking-state.json 唯一权威 + 上下文/伏笔/角色状态/时间线派生视图）
└── 对标/（拆文产出，可选）
```

完整产物协议见 [references/project-files.md](references/project-files.md)；单章流程见 [references/workflow-chapter.md](references/workflow-chapter.md)；质量门禁哲学见 [references/quality-gates.md](references/quality-gates.md)。

## 项目正文与索引不入库

小说项目、向量索引、作者语料与本地配置保存在你自己的目录，不提交到本仓库。
