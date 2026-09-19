# Quattro Intelligence Human-Gold Contract

## Rubric Version

`direct-delegate-human-rubric-v1`

This rubric is defined from the routing contract, not from production router
branches. Reviewers must not inspect Quattro routing code while labeling.

## Reviewer Evidence Boundary

A reviewer may see only:

- the sanitized user request;
- explicitly stated repository or file requirements;
- explicitly stated retrieval or current-information requirements;
- explicitly stated modification, execution, verification, or multi-step needs.

A reviewer must not see deterministic or shadow decisions, reasons,
confidences, selected workers/models/providers/accounts, actual tool or
retrieval use, execution outcomes, validation/build/test results, latency,
retries, fallback behavior, final context size, or downstream outcomes.

Reviewer artifacts contain opaque `br_*` item IDs. The record mapping,
sampling stratum, and disagreement-selection reason remain in the private
SQLite store and are never serialized into the review file or terminal output.

## DIRECT

Choose `DIRECT` when a reliable response can reasonably be produced from the
request and supplied context without external execution. Typical cases include
conversation, explanation, summarization, drafting, comparison, and complex
reasoning that does not require inspecting or changing external state.

## DELEGATE

Choose `DELEGATE` when satisfying the request requires external execution or
state: repository/file inspection, retrieval of current information, tool
orchestration, code or configuration modification, debugging, testing,
building, verification, or substantial multi-step implementation.

## UNCERTAIN

Choose `UNCERTAIN` when the request lacks enough information for a reliable
binary judgment or sits on a genuine boundary. Uncertainty is evidence; it is
not automatically converted to either class.

## Independent Votes and Acceptance

Each reviewer vote is stored independently and append-only with reviewer,
rubric version, reason category, note, and timestamp. Strict blind human-gold
is accepted only when at least two active independent reviewers unanimously
choose the same binary label and no active reviewer chose `UNCERTAIN`.

Legacy exposed reviews remain separate audit evidence. Blind relabeling creates
new votes and a new resolution event; it never overwrites legacy provenance.

## Corrections

Accepted votes cannot be edited. A reviewer correction appends a superseding
vote that references the original and records a correction reason. If active
votes no longer provide reliable consensus, an append-only retraction event
removes that resolution from future datasets without deleting history.

## Sampling

Sampling is stratified across conversational/trivial, factual/explanatory,
current-information/retrieval, repository inspection, small and substantial
code modification, debugging, test/build/verification, research, tool
orchestration, multi-step implementation, and complex reasoning without
execution. Selection may oversample hidden deterministic/shadow disagreements,
but the reviewer is never told that a disagreement exists. Display ordering is
opaque and route-oblivious.
