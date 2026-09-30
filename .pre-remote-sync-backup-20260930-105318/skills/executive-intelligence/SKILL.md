---
name: executive-intelligence
description: Collect and analyze source-grounded executive technology signals from major AI model vendors, then produce auditable trend tables. Use for AI vendor executive statements, official model-roadmap monitoring, or cross-company frontier-model trend reports; do not use for generic news summaries without source verification.
---

# Executive Intelligence

Use the repository's Python pipeline as the execution engine. Keep the skill as an orchestration layer.

## Workflow

1. Locate the repository root containing `main.py`, `config/`, and `src/ai_tech_intelligence/`.
2. Run `python main.py doctor` before collection. Report missing capabilities without printing secret values.
3. Resolve requested company names to IDs with `python main.py list-companies`.
4. For a fresh request, run `python main.py run --companies <ids> --days <days>`. Start with conservative limits when the user did not specify scale.
5. For previously collected data, use `analyze`, `report`, or `eval` separately instead of repeating paid discovery calls.
6. Return the generated `.xlsx` as the primary artifact and summarize source coverage, analysis fallbacks, and evaluation warnings.

## Evidence rules

- Prefer Tier A and B. Tier C may support a conclusion; Tier D is only a lead unless the user explicitly requests broader discovery.
- Do not attribute an official editorial article to an executive unless the source explicitly names the person and links the statement to them.
- Keep `Explicit`, `Strong inference`, and `Speculative` distinct. Describe trend output as inference from public signals.
- If `证据落地校验` fails, call out the row for human review rather than presenting it as verified.
- Preserve source URLs in the report. Never replace direct sources with search-result URLs.

## Configuration boundaries

- Read the project `.env.txt`; never echo values or copy keys into reports.
- Do not enable YouTube automatically. It requires a configured official channel ID and `YOUTUBE_API_KEY`; video metadata is not a transcript.
- Do not modify the vendor/person registry merely to make a single search result pass verification. Add entries only from an official verification source.

See the repository `README.md` for source pricing, YouTube setup, commands, and output definitions.

