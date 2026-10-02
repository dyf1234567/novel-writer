# Quality gates

Use gates proportionally to the operation and project configuration.

## Blocking checks

Block acceptance or publication when any of these applies:

- analysis, TODOs, prompts, or role metadata leaked into manuscript prose;
- a confirmed character, timeline, world-rule, or outline contradiction;
- an invalid chapter state transition;
- a user-defined prohibition is violated;
- an expected output file is incomplete or structurally invalid.

Provide the shortest repair path. Do not force a complete rewrite when a narrow correction is sufficient.

## Degraded checks

Retrieval, a derived index, dashboard generation, or a nonessential analyzer may degrade. On degradation:

1. retry once when the failure is plausibly transient or the index can be rebuilt safely;
2. use a documented fallback such as recent accepted chapters plus canonical memory;
3. record the failure and stale artifact;
4. continue only when no blocking fact is unresolved.

## Optional checks

Outside the default review cadence below, run only when requested, configured, or justified by risk:

- style-metric audit;
- anti-pattern or "AI-like" language scan;
- multi-agent editorial review;
- broad research;
- whole-volume continuity audit;
- dashboard generation.

Regex and metric checks produce evidence, not final literary judgments. Treat unusual prose as a review signal rather than an automatic defect.

`continue-write` defaults to advisory prose metrics. The report still records short length, dialogue ratio, repetition, and other signals, but they do not by themselves fail the chapter gate or trigger padding. `--strict-prose-metrics` explicitly restores numeric blocking for a project that wants it. The Beat Sheet pipeline is also opt-in because its per-beat length targets are hard constraints. Structural contamination, protected reveals, and invalid state transitions remain blocking.

`--auto-batch-review` and `--four-official` generate review task files only. They do not dispatch agents or record an editorial verdict; report the tasks as pending until a reviewer actually completes them.

## Default review cadence

1. **Every chapter — targeted continuity.** Before acceptance, read the draft against relevant accepted passages and confirmed character, timeline, world-rule, and foreshadowing state. Check this chapter's changed facts and causal links; record unresolved conflicts. After acceptance, synchronize relevant memory and indexes.
2. **Every 10 accepted chapters — creative checkpoint and style review.** Before the next chapter, read representative recent prose and review direction, character agency, and pacing with the user or designated reviewer. Compare the prose with the book's confirmed style and character voices; when an author pack is configured, use its selected family and abstract traits. Without a reliable style baseline, report that limitation and assess observable consistency. Prose metrics remain advisory. Record the review notes with the existing checkpoint decision; do not update the style baseline merely to make drift disappear.
3. **Every completed volume — whole-volume audit and multi-agent review.** Collect the volume evidence with `volume_audit.py`; then review the manuscript in bounded batches against relevant state. When collaboration is available, dispatch read-only reviewers for continuity, character and causality, structure and pacing, and style. Supply the project path, chapter range, relevant state, and the review question. Each reviewer reads source prose and returns findings with chapter references and excerpts. The root agent reconciles conflicts, handles edits, and records the volume verdict before advancing.
4. **Major plot decisions — red-team review.** When the user, approved outline, or host identifies a character death, identity reveal, world-rule breakthrough, or comparable irreversible change, review its setup, motives, causal support, consequences, and alternatives before acceptance. Use a read-only red-team agent when available. Respect the confirmed ending and deliberate creative choices; do not reject a surprise solely because it is surprising.

If collaboration tools are unavailable, the host performs the same reviews sequentially and explicitly reports that independent multi-agent review did not run. Task generation is reported as pending until actual review is complete. Confirmed contradictions and user hard constraints require correction; stylistic preferences are suggestions for the author to decide. Store notes in the existing editing/checkpoint artifacts, without adding a new review database or configuration layer.

## Reporting

Return a compact result with:

- `blocking`: failures that prevented acceptance;
- `degraded`: failed subsystems and fallbacks used;
- `optional`: checks run and signals found;
- `accepted`: whether canonical state was updated.
