# Help-desk ticketing

Build a synthetic SQLite dataset that answers historical questions about ticket status, team ownership, and customer replies. An April transfer or reopening must leave the March snapshot reproducible. Design 10-40 related tables and document each table's grain, keys, and relationships.

## Business rules

- Store timestamps in UTC. March spans 2026-03-01 00:00:00 inclusive through 2026-04-01 00:00:00 exclusive. The April snapshot includes events strictly before 2026-05-01 00:00:00.
- A ticket starts open with one owning team. At a cutoff, replay its events in ascending timestamp and then ascending ticket-local sequence number. Each sequence number is unique within the ticket. Tickets created at or after the cutoff are absent from that snapshot.
- Open and pending statuses both contribute to backlog. Closed tickets contribute zero. A reopening is a transition from closed to open or pending. A ticket can reopen more than once. A transfer changes the owning team and preserves status.
- Count each open ticket once under its owning team at the cutoff. Include every team created before that cutoff when a question requests zero counts.
- A public agent reply is a public message from a human support agent following the ticket's first customer message in event order. Private notes, automated acknowledgments, and messages on other tickets do not qualify. Q4 includes tickets of any status.

## Frozen questions

[Q1] Which ticket IDs were open or pending at the end of March 31, 2026?
[Q2] For every team existing at the end of March 31, 2026, return its ID and number of open or pending tickets it owned then, including zero.
[Q3] Which distinct ticket IDs reopened during March 2026 after a previous closure?
[Q4] Which ticket IDs had a customer message by the end of March 31, 2026, but no subsequent public human agent reply on that ticket by then?
[Q5] [ordered] Return up to three team IDs and their positive backlog counts at the end of March 31, 2026, ordered by count descending and then team ID ascending.
[Q6] Which ticket IDs were open or pending at the end of March 31, 2026, and closed at the end of April 30, 2026?

Return one row per qualifying ticket for Q1, Q3, Q4, and Q6. Q2 and Q5 return one row per qualifying team with the ID first and the integer count second. Only Q5 requires a sequence.

## Review and release checks

| Question | Fixture fact | Expected distinction |
|---|---|---|
| Q1 | A pending ticket closes exactly at midnight on April 1. | It belongs in the March snapshot. |
| Q2 | A ticket transfers from A to B exactly at midnight on April 1. B owned no tickets in March. | A gets the ticket in March and B gets a zero row. |
| Q3 | A ticket closed in February reopens twice in March. | Its ID appears once. |
| Q4 | A customer message receives a private note and an automated acknowledgment in March, then a public human reply in April. | Include the ticket. A second ticket with a public human reply in March must drop out. |
| Q5 | Team IDs 10, 20, 30, and 40 have backlogs of 6, 5, 4, and 4. | The result is (10, 6), (20, 5), (30, 4). Reversing the ID tie-break selects team 40. |
| Q6 | Two March-open tickets close in April. One reopens later in April at the same timestamp as its closure, with a higher sequence number. | Only the ticket still closed at the April cutoff qualifies. |

Have the reviewer calculate fixture answers independently and execute a plausible wrong query per question. Probe an ownership event referencing a nonexistent team and verify that SQLite raises a foreign-key violation.

Generate nine seeded Faker worlds, three per split. Assign Q1-Q3 to train, Q4 to validation, and Q5-Q6 to test. Vary ticket IDs, team IDs, event histories, and backlog sizes across seeds. Require each fixture distinction to occur in at least one world in its question's assigned split. For Q5, explicitly compare third and fourth place before truncating the ranking.

Derive expected answers by replaying generated events in Python. Check all six SQL queries in every world before exporting the split-specific examples. Keep SQLite databases and solver prompts separate from evaluator answers. Record seeds, model ID, scenario coverage, first-attempt results, and repairs in the manifest.
