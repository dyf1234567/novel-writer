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

## 来源与许可

本项目包含基于 [leenbj/novel-creator-skill](https://github.com/leenbj/novel-creator-skill) 思路及材料的改编，并已获得原作者公开发布许可。详细说明见 [NOTICE.md](NOTICE.md)。上游未声明开源许可证，本仓库也暂未附加通用开源许可证；公开可见不等于自动授予复制、修改或再分发权。
