# 正文接受、审计与项目策略

## 旧项目迁移

新版索引仅使用内容绑定的已接受章节。原有 `03_manuscript` 文件不会自动算作已接受。先审阅每章正文；对需要保留的文件逐章执行：

```text
python scripts/canonical_state.py status --project-root <项目目录>
python scripts/canonical_state.py accept --project-root <项目目录> --chapter-file <03_manuscript/第N章.md> --reviewer <姓名> --confirm ACCEPT
python scripts/plot_rag_retriever.py build --project-root <项目目录> --engine fts5 --full-rebuild
```

若项目需要向量检索，另外运行向量或 hybrid 建库。接受记录位于项目 `.flow/accepted_chapters/`，保存文件名和 SHA256。正文任何修改都使该章接受状态失效；审阅修订稿后重新接受并建库。审核已存在的门禁记录时，必须先对当前正文重跑门禁。文件名不同的同章号不能同时接受。模板/占位稿不得接受。

同一项目内的 legacy、FTS5、向量索引都核对接受状态和索引内容签名。旧索引缺少签名，必须重建。检索失败时读取当前正稿和已确认记忆，不要把旧缓存当作证据。

## 全卷审计

`collect` 收集章节、状态文件和当前接受状态，生成带内容指纹的待审证据。结构缺项时为 blocked，不能直接 `complete --verdict pass`。修复后重新 `collect` 并进行语义审阅。通过后的正文、记忆或策略发生变化，`status` 返回 stale，卷末检查点也不再视作通过。旧版审计没有指纹，需重新收集；仅修改备注不能让旧结论继续有效。

## 可选节奏策略

项目根目录可创建 `.novel_policy.json`：

```json
{
  "pacing": {
    "enabled": true,
    "max_fast_per_volume": 3,
    "max_consecutive_fast": 1,
    "slow_density_window": 4
  },
  "narrative": {
    "avoid_resolution": true,
    "quota_abc": false,
    "cliffhanger": false,
    "finale_chapters": [60]
  }
}
```

文件不存在时，这些节奏和断章偏好关闭。不要创建该文件来套用通用网文配额；与用户选定题材、结构和结尾相符时再逐项启用。已确认的禁揭示信息仍是事实保护约束，不随偏好关闭。无效字段或类型应让门禁失败并报告错误。`finale_chapters` 中的终局章不执行“不能收束”等写作偏好，但仍需检查禁揭示信息。

`continue-write` 默认将字数、对话比例、段落重复度等数值检查写入质量报告作为提示，不因这些指标单独拦稿或自动填充。若本书明确需要数值硬门槛，增加 `--strict-prose-metrics`；`--use-beat-sheet` 也须主动开启，其每个 Beat 的展开目标会作为该模式的要求。广泛调研、每十章批量审稿任务、四官审稿任务和定期风格基准更新均默认关闭，分别可用 `--auto-research`、`--auto-batch-review`、`--four-official`、`--auto-style-update` 开启。任务文件不是已完成的多 Agent 审稿结论。

`creative_checkpoint.py approve` 记录审阅者、说明及审阅时的输入指纹。此后改动相关已完成章节或追踪文件，旧批准失效，需要再次审阅。
