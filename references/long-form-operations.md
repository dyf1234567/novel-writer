# 长篇运营

长连载、多卷作品，或预期超过约 30 万汉字的项目读本参考。

## 本地混合检索

使用 `hybrid` 检索把精确词法召回与本地语义召回结合。FTS5 仍是确定性兜底；向量失败属于降级，必须如实报告，不得冒充 hybrid 成功。

向量索引只收录内容绑定的已接受正文段落。不得索引未入规范的草稿、原作者语料、提示词或审阅报告。修订已接受章节后，先重审、重接受、重建索引再做检索；见 [project-policy.md](project-policy.md)。

支持的本地 embedding 提供方：

- `ollama`：默认本地 HTTP 端点，适合单独管理的 GPU 模型；
- `sentence-transformers`：使用当前 Python 环境，可用时启用 CUDA；
- `hash`：仅用于确定性测试，绝不把它描述为语义检索。

对 RTX 4060（8 GB 显存），优先选择能与用户生成负载从容共存的 embedding 模型。Ollama 上的 `bge-m3` 是默认的偏质量选项；并发显存吃紧时改用更小的中文 embedding 模型。

命令：

```text
scripts/plot_rag_retriever.py build --project-root <路径> --engine hybrid
scripts/plot_rag_retriever.py query --project-root <路径> --query <文本> --engine hybrid --auto-build
```

环境变量默认值为 `NOVEL_VECTOR_PROVIDER`、`NOVEL_VECTOR_MODEL`、`NOVEL_VECTOR_OLLAMA_URL`。未经用户授权，不下载模型、不安装 Python 包。

## 全卷审计

在确认的卷边界处运行：

```text
scripts/volume_audit.py collect --project-root <路径> --volume <n>
```

脚本生成结构性证据与语义审阅清单。将正文证据对照人物、时间线、世界规则、伏笔、卷承诺与受保护伏笔揭示进行审阅。执行 `quality-gates.md` 描述的卷边界多 Agent 审稿，然后记录一个判定：

```text
scripts/volume_audit.py complete --project-root <路径> --volume <n> --verdict pass --reviewer <姓名> --notes <摘要>
scripts/volume_audit.py complete --project-root <路径> --volume <n> --verdict needs_revision --reviewer <姓名> --notes <摘要>
```

审计缺失、待处理、blocked 或标记 `needs_revision` 时，不得跨越必需的卷边界推进。

## 人工创作检查点

默认节奏为每 10 个已接受章节一次、每个卷边界一次。每个 10 章检查点上，按 `quality-gates.md` 的要求抽查近期代表性文段、复核风格与人物声音；然后决定继续、修订大纲、删除或合并剧情线、调整节奏、还是停止。风格复核结论写入检查点记录。卷边界处，把多 Agent 审稿发现纳入卷判定。

起草目标章节之前先查状态：

```text
scripts/creative_checkpoint.py status --project-root <路径> --next-chapter <n> --interval 10
```

记录用户或指定审阅者的决策：

```text
scripts/creative_checkpoint.py approve --project-root <路径> --after-chapter <n> --reviewer <姓名> --notes <决策>
scripts/creative_checkpoint.py reject --project-root <路径> --after-chapter <n> --reviewer <姓名> --notes <需修改项>
```

到期检查点未获批准时，`continue-write` 在改动正文之前停下。绝不虚构人工批准。关闭检查点需要显式的项目或用户选择；「自动流程跑得顺」不构成充分理由。
