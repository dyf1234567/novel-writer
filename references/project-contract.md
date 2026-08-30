# Project contract

Read this reference for drafting, continuity inspection, or any operation that changes durable project state.

## Ownership of facts

Use this precedence when facts conflict:

1. explicit user correction or confirmation;
2. accepted manuscript chapters;
3. approved outline and world rules;
4. structured trackers and graph state;
5. generated chapter summaries;
6. retrieval results and model inference.

Never overwrite a higher-precedence source with a lower-precedence inference.

## Expected project areas

Existing projects may use different names. Map by purpose instead of forcing a migration:

- planning: premise, outline, volume and chapter anchors;
- memory: characters, world state, timeline, foreshadowing, chapter summaries;
- manuscript: accepted chapter prose;
- retrieval: indexes and passage metadata derived from accepted prose;
- editing: audit reports, repair plans, and noncanonical drafts.

Create only directories the selected workflow needs. Preserve additional user files.

## Chapter state transitions

Use explicit transitions:

```text
planned -> drafted -> reviewed -> accepted -> indexed
                   \-> needs_revision
```

- `drafted` prose is not canonical memory.
- `accepted` requires user acceptance or the project's configured automation policy plus all blocking checks.
- only accepted chapters enter durable summaries, graphs, and retrieval indexes.
- revision of an accepted chapter invalidates derived summaries, graph facts, and retrieval entries for that chapter until rebuilt.

## Continuity context

Prefer a compact context assembled from relevant state over reading the entire project. Include:

- the current anchor and goal;
- recent accepted chapter summaries;
- active characters and their aliases, locations, capabilities, and relationships;
- timeline constraints;
- unresolved and due foreshadowing;
- retrieved passages supporting current entities or plot threads;
- cascade warnings caused by outline changes.

When a retrieval result conflicts with canonical state, surface the conflict instead of blending both versions.

## Safe mutations

- Make narrow updates after each accepted chapter.
- Before a broad outline revision, identify the affected chapter range and preserve recoverable prior state.
- Rebuild only derived artifacts affected by the change.
- A failed optional or derived update should not corrupt accepted manuscript text.
- Never edit the user's source corpus or external author pack as part of a novel chapter workflow.
