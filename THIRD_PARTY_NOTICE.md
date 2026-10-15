# 第三方组件声明

本仓库的写作工艺层源自以下 MIT 许可项目，按 MIT 许可证条款保留其版权声明：

- 项目：oh-story-claudecode（skills/story-long-write 及 story-deslop）
- 地址：https://github.com/zenstory-ai/oh-story-claudecode
- 许可：MIT License（见下方全文）

包含内容：scripts/ 下的 build_writer_prompt.py、storyctl.py、tracking_commit.py、
outline_view.py、check-ai-patterns.js、check-degeneration.js、normalize-punctuation.js、
check-outline-contract.js、check-outline-copy.js、style-whitelist.js、wordcount_core.py、
author_memory_commit.py、build_architect_brief.py，以及 references/ 下的全部写作
方法论文档（workflow-*、writing-craft、long-*、tracking-*、banned-words、deslop-gates、
anti-ai-writing 等）。

本地修改：plot_rag_retriever.py 的检索层、style-writer 桥接与 SKILL.md 的流程
融合为本仓库新增。

本仓库对上游文件另有以下改动，同步上游时需手工比对：

- `scripts/normalize-punctuation.js`：放过 markdown 表格分隔行与 URL 内的横线省略号；
  新增 `--json`，逐条回传已应用的替换并附破折号功能复核提示。
- `scripts/check-ai-patterns.js`：`em-dash` 规则跳过 URL 区间内的横线。
- `scripts/storyctl.py`：`chapter check --fix-punctuation` 以 `punctuation_changes`
  数组返回改写明细，取代原先的 `punctuation_fixed` 布尔值。
- `scripts/inline-spans.js`：本仓库新增的共享判定模块（URL 区间），供上面两个检测器使用。

其余文件保持上游原样。

---

MIT License

Copyright (c) 2025-2026 oh-story-claudecode

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
