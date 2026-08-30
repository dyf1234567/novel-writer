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

Run only when requested, configured, or justified by risk:

- style-metric audit;
- anti-pattern or "AI-like" language scan;
- multi-agent editorial review;
- broad research;
- whole-volume continuity audit;
- dashboard generation.

Regex and metric checks produce evidence, not final literary judgments. Treat unusual prose as a review signal rather than an automatic defect.

## Suggested cadence

- every accepted chapter: state synchronization and targeted continuity check;
- at project-defined checkpoints: broader character, timeline, and foreshadowing audit;
- every configured chapter interval: require a recorded human creative decision before drafting the next chapter;
- at each completed volume: collect a whole-volume evidence pack and record `pass` or `needs_revision` before advancing;
- before release: manuscript contamination, continuity, formatting, and source-overlap checks;
- multi-agent review: explicit request, high-risk milestone, or configured checkpoint rather than automatically every chapter.

## Reporting

Return a compact result with:

- `blocking`: failures that prevented acceptance;
- `degraded`: failed subsystems and fallbacks used;
- `optional`: checks run and signals found;
- `accepted`: whether canonical state was updated.
