# Long-form operations

Read this reference for long serials, multi-volume fiction, or projects expected to exceed roughly 300,000 Chinese characters.

## Local hybrid retrieval

Use `hybrid` retrieval to combine exact lexical recall with local semantic recall. FTS5 remains the deterministic fallback; vector failure is degraded and must be reported rather than silently presented as hybrid success.

The vector index contains accepted manuscript passages only. It must not index noncanonical drafts, source-author corpora, prompts, or review reports. Rebuild affected chapters after an accepted revision.

Supported local embedding providers:

- `ollama`: default local HTTP endpoint, suitable for a separately managed GPU model;
- `sentence-transformers`: uses the active Python environment and CUDA when available;
- `hash`: deterministic test provider only, never describe it as semantic retrieval.

For an RTX 4060 with 8 GB VRAM, prefer an embedding model that comfortably fits alongside the user's generation workload. `bge-m3` through Ollama is the default quality-oriented option; use a smaller Chinese embedding model when concurrent VRAM pressure matters.

Commands:

```text
scripts/plot_rag_retriever.py build --project-root <path> --engine hybrid
scripts/plot_rag_retriever.py query --project-root <path> --query <text> --engine hybrid --auto-build
```

Environment defaults are `NOVEL_VECTOR_PROVIDER`, `NOVEL_VECTOR_MODEL`, and `NOVEL_VECTOR_OLLAMA_URL`. Do not download a model or install Python packages without user authorization.

## Whole-volume audit

At a confirmed volume boundary, run:

```text
scripts/volume_audit.py collect --project-root <path> --volume <n>
```

The script creates structural evidence and a semantic review checklist. Automatic collection is not approval. Review manuscript evidence against characters, timeline, world rules, foreshadowing, volume promises, and protected reveals, then record one verdict:

```text
scripts/volume_audit.py complete --project-root <path> --volume <n> --verdict pass --reviewer <name> --notes <summary>
scripts/volume_audit.py complete --project-root <path> --volume <n> --verdict needs_revision --reviewer <name> --notes <summary>
```

Do not advance across a required volume boundary while the audit is missing, pending, blocked, or marked `needs_revision`.

## Human creative checkpoints

Default cadence is every 10 accepted chapters and every volume boundary. A checkpoint is a creative decision, not a statistical quality check. Inspect at least one relevant manuscript chapter and decide whether to continue, revise the outline, remove or merge a plot line, change pacing, or stop.

Check status before drafting the target chapter:

```text
scripts/creative_checkpoint.py status --project-root <path> --next-chapter <n> --interval 10
```

Record the user's or designated reviewer's decision:

```text
scripts/creative_checkpoint.py approve --project-root <path> --after-chapter <n> --reviewer <name> --notes <decision>
scripts/creative_checkpoint.py reject --project-root <path> --after-chapter <n> --reviewer <name> --notes <required changes>
```

`continue-write` stops before manuscript mutation when a due checkpoint is not approved. Never invent human approval. Disabling checkpoints requires an explicit project or user choice; a convenient automatic run is not sufficient reason.

