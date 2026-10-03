---
name: novel-writer
description: Manage an established or newly created Chinese long-form fiction project when work requires persistent chapter state, continuity retrieval, outline-aware drafting, revision, or release checks. Use for multi-chapter novels and serial fiction; do not activate for an isolated short story, a single prose rewrite, or author-style extraction alone.
---

# Novel Writer

Coordinate long-form fiction without treating one writing recipe as universally correct. Preserve the user's creative authority while keeping project state recoverable and internally consistent.

## Route the request

Choose one primary mode before loading detailed guidance:

- **Create or plan a project**: read [workflows.md](references/workflows.md), sections "Create" and "Plan".
- **Explore plot alternatives, opening strategy, character agency, or pacing**: read [creative-toolkit.md](references/creative-toolkit.md) when the request warrants writing guidance.
- **Design important characters, key relationship scenes, or diagnose weak motivation**: read [character-tension.md](references/character-tension.md). Use its cards selectively; ordinary scenes do not require them, and trauma, masks, or tragic outcomes are never mandatory.
- **Draft or continue chapters**: read [workflows.md](references/workflows.md), section "Draft and continue", plus [project-contract.md](references/project-contract.md).
- **Revise an existing chapter or outline**: read [workflows.md](references/workflows.md), section "Revise". Never infer permission to rewrite unaffected chapters.
- **Inspect status, continuity, characters, timeline, or foreshadowing**: read [project-contract.md](references/project-contract.md). Inspection alone does not authorize edits.
- **Run editorial or release checks**: read [quality-gates.md](references/quality-gates.md).
- **Operate a long serial or million-word project**: read [long-form-operations.md](references/long-form-operations.md) for hybrid retrieval, whole-volume audits, and human checkpoints.
- **Accept older chapters, configure gates, or recover an audit**: read [project-policy.md](references/project-policy.md).
- **Apply an author-derived style pack**: read [style-integration.md](references/style-integration.md). Keep source lore disabled unless the user explicitly requests adaptation or fan fiction.

For a standalone short story or a one-off paragraph, write directly without initializing the long-form project machinery unless the user asks to turn it into a managed novel project.

## Establish project context

Before changing a project:

1. Resolve the project root from the user's path or the current workspace. Do not invent a project location.
2. Inspect existing state and configuration. Preserve unknown fields and user-authored notes.
3. Determine whether the request is read-only, a draft, a revision, or a state transition.
4. Use the smallest workflow that satisfies the request. Do not run research, multi-agent review, style imitation, or batch writing merely because the project supports them.

When creating a new project, confirm only choices that materially affect the result: premise, target length, viewpoint, desired level of automation, and any non-negotiable constraints. Offer defaults when the user is unsure.

## State invariants

The project files are durable state; chat history is not.

- Keep manuscript text separate from plans, review notes, prompts, and tool output.
- Do not silently change confirmed outline anchors, character facts, timeline facts, or resolved foreshadowing.
- Record the chapter or revision that changed a durable fact.
- Treat generated summaries as fallible evidence, not unquestionable truth. Prefer manuscript text and user-confirmed facts when sources conflict.
- After an accepted chapter, update relevant project memory and retrieval indexes. Drafts rejected by the user or failed by a blocking check must not enter canonical memory.
- Verify a chapter's content-bound acceptance record before indexing or using historical passages. An older project needs explicit adoption; do not silently trust files merely because they reside in the manuscript directory.
- Preserve recoverability before a broad outline cascade or multi-file rewrite.

Detailed state ownership and transitions are in [project-contract.md](references/project-contract.md).

## Drafting contract

Assemble only the context needed for the current chapter:

1. current outline anchor and chapter goal;
2. recent chapter summaries;
3. relevant characters, locations, timeline facts, active plot threads, and foreshadowing;
4. retrieved historical passages when continuity risk warrants them;
5. optional style context;
6. explicit user constraints.

Generate clean manuscript prose. Never place analysis labels, TODOs, role descriptions, or review commentary inside the manuscript region.

Pacing quotas and cliffhanger frequency are opt-in project policies. The `continue-write` CLI records prose metrics as advisory signals by default; use `--strict-prose-metrics` only when the user wants numeric thresholds to block acceptance. An explicit Beat Sheet mode may enforce its own beat targets. Do not treat metric success as literary approval.

Apply the default review cadence in [quality-gates.md](references/quality-gates.md): targeted continuity every chapter, a creative checkpoint and style review every 10 accepted chapters, whole-volume audit and multi-agent review at volume endings, and red-team review of major irreversible plot decisions. The host performs these semantic reviews and reports completed, pending, or unavailable; scripts alone do not complete them.

## Quality levels

Checks have three severities:

- **Blocking**: manuscript contamination, confirmed fact contradiction, invalid state transition, or a user-defined hard constraint. Stop before publishing or updating canonical memory.
- **Degraded**: retrieval unavailable, a nonessential index stale, or an optional analyzer failed. Continue only with an explicit warning and a recorded fallback.
- **Optional outside the scheduled cadence**: additional style audits and multi-agent reviews, humanization passes, dashboards, and broad research unless the project configuration elevates them.

Do not claim that a workflow guarantees consistency at any word count. Report which checks ran, which were skipped, and what remains uncertain. See [quality-gates.md](references/quality-gates.md).

## Script execution

Scripts live in `scripts/`. Resolve Python portably:

1. use `NOVEL_WRITER_PYTHON` when configured;
2. otherwise use the active Python executable available in the environment;
3. on Windows, the `py` launcher is an acceptable fallback.

Never embed a user-specific absolute interpreter path in generated project files or instructions.

Primary entry points:

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
```

Inspect `--help` before constructing a command whose arguments are not already established. Use scripts for deterministic state manipulation; use model judgment for prose, semantic review, and creative tradeoffs.

## Completion report

For mutations, report:

- what manuscript or state changed;
- whether canonical memory and indexes were updated;
- blocking, degraded, and optional checks that ran;
- any unresolved risk or user decision.

Do not equate a passing regex or schema check with literary quality.
