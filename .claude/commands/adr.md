---
description: Guided flow to draft a new Architecture Decision Record under docs/adr/ with auto-numbering and index update.
---

You will guide the user through creating a new ADR using the Michael Nygard format adopted for this project (Title, Status, Context, Pre-decision review, Decision, Consequences, plus an explicit Alternatives Considered section).

## Step 1 — Determine the next ADR number

Run `ls docs/adr/ 2>/dev/null | grep -E '^[0-9]{4}-' | sort | tail -1` to find the highest existing ADR number. Increment by one and pad to 4 digits. If `docs/adr/` does not exist or is empty, start at `0001`.

## Step 2 — Gather the inputs

Ask the user for the following, **one at a time** unless they pass all of them in `$ARGUMENTS`:

1. **Title** — short imperative phrasing, kebab-case-friendly. Example: `Athena over Redshift`.
2. **Status** — one of: `Proposed`, `Accepted`, `Deprecated`, `Superseded by ADR-NNNN`. Default `Proposed` if not stated.
3. **Context** — what forces are at play, what problem is being solved. Encourage 2-4 short paragraphs. If the user is terse, prompt for the *constraints* (cost, time, ecosystem) and the *triggers* (what happened that requires this decision now).
4. **Decision** — the actual choice in declarative voice ("We will use X"). Include enough specificity that a reader six months from now does not need archaeology.
5. **Consequences** — both positive and negative. Force the user to name at least one negative consequence; "all upside" is a smell.
6. **Alternatives considered** — at least one realistic alternative with one sentence on why it was not chosen. "We considered nothing" is not acceptable; if true, surface that as a process failure and ask the user to come back when at least one alternative has been thought through.

If the user invokes the command with `$ARGUMENTS` containing partial info, parse what is there and only ask for the missing fields.

## Step 2.5 — Pre-decision review (mandatory)

Before composing the file, ask the user the four pre-decision review questions and require a one-line answer to each. The answers persist inside the ADR (see template) so future readers see what was thought through and what was not.

The four questions:

1. **Failure mode in 6 months** — What is the concrete scenario where this decision breaks down? (Not "anything could happen" — a specific scenario.)
2. **Prior art and divergence** — Who else has faced this problem, what did they choose, and why are we choosing differently? (If the answer is "nobody else has this problem", that is itself a smell — re-examine the framing.)
3. **Cost of reversal** — If we are wrong, what does it cost to undo? Hours / days / weeks? Bound it.
4. **Early warning signal** — What concrete metric, log line, or observation tells us the decision was wrong **before** it hurts?

Stop conditions — escalate back to the user, do not compose the ADR:

- The user answers "no sé" / "no pensé" / equivalent to **2 or more** of the four questions. The decision is not mature; the right move is to defer, not to record.
- Question 3 ("cost of reversal") answered "very high / irreversible" without question 4 having a strong answer. An irreversible decision without an early warning signal is the highest-risk category — recommend pausing to think before recording.

If all four are answered, proceed to Step 3 with the answers held in memory for the template.

## Step 3 — Compose the ADR file

Filename pattern: `docs/adr/NNNN-<kebab-case-slug>.md`. The slug is derived from the title.

The file content follows this template exactly:

```markdown
# ADR-NNNN — <Title>

- **Status**: <Status>
- **Date**: <YYYY-MM-DD>  <!-- today's date in UTC -->
- **Tags**: <2-5 short tags: aws, storage, orchestration, etc.>

## Context

<2-4 paragraphs as gathered>

## Pre-decision review

<!-- Answers gathered in Step 2.5. One line each. Verbatim from the user; do not paraphrase. -->

- **Failure mode in 6 months**: <…>
- **Prior art and divergence**: <…>
- **Cost of reversal**: <…>
- **Early warning signal**: <…>

## Decision

<the actual choice, declarative voice>

## Consequences

### Positive

- …
- …

### Negative

- …
- …

### Neutral / open questions

- …

## Alternatives considered

### <Alternative A>

<one paragraph on what it was and why it was not chosen>

### <Alternative B>

<one paragraph>

## References

- <links to AWS docs, blog posts, prior art>
- <related ADRs: supersedes / superseded-by / related>
```

## Step 4 — Update the ADR index

Open or create `docs/adr/index.md` and ensure it contains a row for the new ADR. The index format:

```markdown
# Architecture Decision Records

Living catalogue of architectural decisions. Each row links to the full ADR.

| #    | Title                              | Status     | Date       | Tags                  |
| ---- | ---------------------------------- | ---------- | ---------- | --------------------- |
| 0001 | [Athena over Redshift](0001-athena-over-redshift.md) | Accepted   | 2026-05-08 | aws, query-engine    |
| 0002 | …                                  | …          | …          | …                     |
```

Insert the new row in numerical order. If the index file does not exist, create it with the table header and the single new row.

## Step 5 — Final hand-off

Show the user:

1. The path of the new file.
2. The first 30 lines as a sanity check.
3. A reminder to commit with a message of the form `docs(adr): NNNN <title>`.

## Notes

- Do not run any LLM call beyond the conversational interaction with the user; this command is reasoning + file IO only.
- If the user wants to revise an existing ADR, do not edit it in place: create a new ADR with status `Supersedes ADR-NNNN`, and update the old one's status to `Superseded by ADR-MMMM`. Decisions are append-only; their *interpretation* through status changes is the historical record.

Context for this invocation: $ARGUMENTS
