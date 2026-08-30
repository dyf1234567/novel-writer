# Author-style integration

Read this reference only when a project uses an author-derived style pack or the user asks for style transfer.

## Separation of concerns

Keep three stores independent:

- author style: transferable language, narrative, and scene features;
- source lore: original characters, settings, events, and terminology;
- project memory: the user's characters, setting, timeline, and plot.

Source lore is disabled by default. Enabling an author style must not enable original-world retrieval.

Pure-style mode also omits verbatim source excerpts. Inject only abstract traits
and retrieval-derived metrics. Source excerpts require the user's explicit
request and `--style-source-excerpts`; never enable this flag from `style_author`
alone.

## Author pack location

Author corpora and indexes are mutable user data and do not belong inside this Skill. Resolve them in this order:

1. an explicit `--authors-root` argument;
2. `AUTHOR_STYLE_HOME`;
3. a project configuration value;
4. the user's data directory fallback implemented by the script.

Never copy a source corpus into a novel project or cloud prompt wholesale.

The preferred provider is the independent `style-writer` Skill. Locate it from
`STYLE_WRITER_SKILL_HOME` or as a sibling of `novel-writer`. Its stable callable
interface is `scripts/style_engine.py::prepare_context(author, query, ...)`.
If it is absent or its pack cannot be resolved, `style_fewshot.py` may fall back
to the legacy local `style_corpus` store.

Use `STYLE_INDEX_HOME` for machine-local indexes and a pack-specific environment
variable such as `JIANGNAN_CORPUS_ROOT` for source files. Neither path belongs in
the novel project. The author pack remains usable in static-profile mode when an
index, embedding model, or embedding server is unavailable.

## Style context

Assemble a compact style context from:

- stable author-level features;
- one dominant work family or period;
- current genre and scene features;
- the project's own character voices;
- a small diverse set of retrieved reference passages;
- negative constraints preventing source characters, lore, catchphrases, and close paraphrase.

Do not average incompatible periods by default. Use automatic routing when metadata makes the choice clear; otherwise state the chosen family or ask when the choice would materially change the result.

Pin a family with `style_family` in `.novel_writer_config.yaml` or with
`--style-family`. The command-line value wins. If neither is present, use the
author pack's `default_family` and report it in the prepared context.

## Output checks

Use metric audits as soft evidence unless a project explicitly defines a hard band. Before release or sharing, run source-overlap checks and inspect flagged passages. Never claim authorship by the reference author or present generated work as an official continuation.
