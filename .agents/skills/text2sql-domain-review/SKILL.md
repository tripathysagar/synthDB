---
name: text2sql-domain-review
description: Review a SynthDB domain schema and its Text2SQL examples against the target questions in the domain brief.
---

1. Freeze the brief's question IDs before design. For each question define the result grain, columns, duplicate handling, and any zero or cutoff rules. Mark sequence-sensitive questions `[Q1] [ordered] ...` and choose fixture rows that expose a reversed sort.
2. Independently derive literal answers from a small fixture. For every ID, execute the gold SQL and one plausible same-shape alternative with a single incorrect business assumption. Record which fixture fact distinguishes them.
3. Test a broken relationship. Identify the expected constraint and show SQLite rejects the row for that reason.
4. Before dataset release, vary the IDs carrying edge cases across seeds. Keep question families together across splits and report first-attempt passes separately from repaired answers.
