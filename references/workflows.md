# Workflows

Load only the section matching the current request.

## Create

Collect or infer a concise project card:

- premise and genre;
- viewpoint and tense;
- target scope;
- automation level: manual, checkpointed, or automatic;
- user-defined hard constraints.

Initialize planning, memory, manuscript, and editing areas. Do not build retrieval indexes before accepted manuscript content exists. Generate an outline at the granularity the user requested; a short serial does not require a million-word roadmap.

## Plan

Develop or inspect the premise, character arcs, world rules, volumes, and chapter anchors. Separate confirmed decisions from suggestions. Do not mark proposed details as canonical until accepted under the project's automation policy.

For important character design or key relationship decisions, selectively use [character-tension.md](character-tension.md). Keep filled cards in the project's existing planning area, mark proposals and evidence, and do not require trauma, hidden masks, or tragic endings. Ordinary scenes and already credible characters need no full card.

## Draft and continue

1. Inspect the current chapter state and last accepted chapter.
2. Assemble continuity context according to `project-contract.md`.
3. Determine the chapter goal and any user direction.
4. Retrieve historical passages only when they reduce a real continuity risk.
5. Load optional style context when configured.
6. Draft clean prose.
7. Run blocking checks and targeted semantic continuity review. Apply the default review cadence in `quality-gates.md`; run other checks according to configuration.
8. If accepted, update memory and derived indexes. Otherwise store the draft outside canonical manuscript state.

For batch writing, complete the state transition for one chapter before drafting the next. Pause at configured checkpoints or when a blocking conflict requires creative judgment.

For long serials, when a 10-chapter creative checkpoint is due, review recent prose for style consistency before recording the creative decision, and stop before creating or modifying the target chapter until the checkpoint is resolved. At a volume boundary, collect a whole-volume audit, perform the scheduled multi-agent review, and record the verdict before checkpoint approval. Review major irreversible plot decisions with the red-team role before accepting the chapter. Use hybrid retrieval when configured; if local embeddings fail, report the degraded FTS5 fallback.

## Revise

### Chapter revision

- Identify the exact accepted chapter and requested scope.
- Preserve unrelated prose and user edits.
- Re-run checks relevant to the changed content.
- Invalidate and rebuild that chapter's summaries, graph updates, and retrieval entries after acceptance.

### Outline revision

- Ask for the earliest affected chapter only when it cannot be inferred safely.
- Preserve a recoverable snapshot of affected planning and derived state.
- Recalculate affected anchors.
- Mark downstream facts as pending review instead of silently deleting them.
- Rebuild affected indexes after the revised outline is confirmed.

Failure of a derived rebuild is degraded, not proof that the outline revision failed. Record the stale artifact and recovery command.

## Inspect

Status, continuity, character, timeline, and foreshadowing requests are read-only unless the user also asks for correction. Report evidence sources and uncertainty. Do not run the drafting pipeline for inspection alone.
