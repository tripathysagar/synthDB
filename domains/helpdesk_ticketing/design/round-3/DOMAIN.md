# DOMAIN.md — Help-Desk Ticketing (Synthetic Text2SQL Dataset)

This document specifies the domain model, the replay semantics for time-cutoff
snapshots, the review/release plan for the six frozen questions (Q1–Q6), and
the evidence gathered so far. Schema: `schema.sql` (SQLite, 25 tables).
Target questions: help-desk ticket status, team ownership, and customer replies.

Revision note: this revision incorporates the **executed** review run — the
frozen fixture was loaded, all six gold questions were run, one plausible
same-shape wrong query per question was run against the same fixture, and nine
broken-relationship probes were executed. All six gold queries returned the
expected row sets and every probe was rejected with
`SQLITE_CONSTRAINT_FOREIGNKEY` (§12). What remains before dataset release is
the fixture→worlds stage: nine seeded Faker worlds across the three splits, the
Python-replay cross-check in every world, and the manifest (§8, §11).

## 1. Purpose and scope

Build a synthetic SQLite dataset that answers **historical** questions about
tickets — what the state of the world was at the end of March 2026, and how it
differs at the end of April 2026. The dataset is event-sourced: every business
change is an immutable row in `ticket_events` (plus at most one typed detail row
in a 1:1 child table). Current/historical state is always **replayed** from
events, never stored as a mutable column on `tickets`. Snapshots are derived
caches keyed by cutoff, so an April transfer or reopening can never rewrite the
March snapshot.

Frozen brief facts:

- Timestamps are UTC. March spans `2026-03-01 00:00:00` inclusive through
  `2026-04-01 00:00:00` exclusive. The April snapshot includes events strictly
  before `2026-05-01 00:00:00`.
- A ticket starts **open** with one owning team. At a cutoff, replay its events
  in ascending `(occurred_at, seq)`; `seq` is unique per ticket. Tickets created
  at or after the cutoff are absent from that snapshot.
- `open` and `pending` contribute to backlog; `closed` contributes zero. A
  **reopening** is a transition from `closed` to `open`/`pending`; a ticket may
  reopen more than once. A **transfer** changes the owning team and preserves
  status.
- Count each open ticket once under its owning team at the cutoff. Include
  every team created before that cutoff when a question requests zero counts.
- A **public agent reply** is a public message from a human support agent
  following the ticket's first customer message in event order. Private notes,
  automated acknowledgments, and messages on other tickets do not qualify.
  Q4 includes tickets of any status.

## 2. Conventions and invariants

1. **Time**: all timestamps are UTC `TEXT` in `YYYY-MM-DD HH:MM:SS`
   (enforced by `GLOB` checks). Lexicographic comparison is chronological.
   Cutoffs are exclusive upper bounds:
   - March snapshot: events with `occurred_at < '2026-04-01 00:00:00'`
   - April snapshot: events with `occurred_at < '2026-05-01 00:00:00'`
2. **Replay order**: ascending `occurred_at`, then ascending ticket-local `seq`.
   Same-timestamp ties are broken by `seq` (see Q6: a closure and a reopening
   at the same timestamp are ordered by sequence number). Note the asymmetry:
   replay is sequence-sensitive for **all** questions, but only **Q5** is
   sequence-sensitive in its *result* (output ORDER BY). Q6 needs `seq` in the
   replay, not in the output.
3. **Foreign keys**: SQLite does **not** enforce them by default. Every session
   must run `PRAGMA foreign_keys = ON;`. The release probe (§8.4) inserts an
   assignment referencing a nonexistent team and must observe
   `FOREIGN KEY constraint failed` (`SQLITE_CONSTRAINT_FOREIGNKEY`). In the
   executed review all nine probes were rejected under the pragma (§12.2).
4. **Composite FK idiom**: detail tables reference
   `ticket_events (event_id, ticket_id)`, backed by the unique index
   `UNIQUE (event_id, ticket_id)`. This makes it impossible for a status row
   to disagree with its event about the parent ticket.
5. **Creation event**: the ticket's first event (`seq = 1`, type `created`)
   carries **both** a `ticket_status_events` row (`from_status = NULL`,
   `to_status = 'open'`) and a `ticket_assignment_events` row
   (`from_team_id = NULL`, `to_team_id = <initial team>`). Both detail rows
   point at the same `event_id`. Replay therefore needs no special-cased
   initial state beyond "process events in order".
6. **Append-only**: events are never updated or deleted after generation.
   `tickets.created_at` always equals the `occurred_at` of the ticket's
   `created` event (generator invariant; verified by construction, not by a
   trigger, to keep the schema DDL-only and portable).
7. **No mutable state on `tickets`**: current status/owner are *derived*.
   This is what makes the March snapshot reproducible after April writes.
8. **Snapshot caches** (`reporting_snapshots`, `snapshot_ticket_states`,
   `snapshot_team_backlogs`) may be materialized for convenience, but are
   always rebuildable by replay and are never hand-edited. Any answer key
   derived from them must be cross-checked against a pure replay.
9. **Status catalog**: `ticket_statuses` seeds `open`/`pending`/`closed` with
   `counts_as_backlog = 1/1/0`. `event_types` seeds `created`,
   `status_changed`, `team_transferred`, `message`.
10. **Seed data is DML**, not DDL: the generator (Faker, see §8) inserts these
    reference rows; `schema.sql` stays pure DDL.

## 3. Replay semantics (normative)

Given a cutoff `T` (exclusive) and a ticket with `created_at < T`:

```
state := absent
for event in SELECT ... FROM ticket_events e JOIN detail tables
            WHERE e.ticket_id = :ticket AND e.occurred_at < :T
            ORDER BY e.occurred_at ASC, e.seq ASC:
    if event.type == 'created':            state := (status='open', team=assignment.to_team_id)
    if event.type == 'status_changed':     state.status := status_detail.to_status
                                           # closed -> open|pending is a reopening (any count)
    if event.type == 'team_transferred':   state.team   := assignment_detail.to_team_id
                                           # status preserved; NO status event is written
    if event.type == 'message':            # does not change status or ownership
        track messages for the Q4 reply rule
```

Derived facts at cutoff `T`:

- Ticket is present in the snapshot iff `tickets.created_at < T`.
- `status` = `to_status` of the ticket's **last** `ticket_status_events` row
  with `occurred_at < T` (the `created` row guarantees one exists).
- `owning_team_id` = `to_team_id` of the ticket's **last**
  `ticket_assignment_events` row with `occurred_at < T`.
- Backlog membership iff `status IN ('open','pending')` (equivalently
  `ticket_statuses.counts_as_backlog = 1`).
- **Reopening** iff a status event has `from_status = 'closed'` and
  `to_status IN ('open','pending')`. A ticket may reopen multiple times;
  each is a separate event, all visible to Q3, but Q3 returns the ticket ID
  **once** (`SELECT DISTINCT`).
- **Transfers** change ownership with status untouched, so a transfer exactly
  at midnight on April 1 is *not* part of the March snapshot: the ticket is
  counted under the old team in March, and the new team gets **no** ticket in
  March (and a zero row in Q2).
- Teams "existing at cutoff" = `teams.created_at < T` (strictly before; a team
  created exactly at the cutoff is excluded — see Open Questions, §10).

**Q4 reply rule (normative, aligned with the checked gold query in §6/§12)**:
let `F` be the ticket's first `message` event
from `author_kind='customer'` with `occurred_at < T`, ordered by
`(occurred_at, seq)`. A ticket qualifies iff `F` exists and there is **no**
later `message` event with `occurred_at < T` (same ticket, strictly after `F`
in `(occurred_at, seq)` order) such that:

```
m.author_kind = 'agent'
AND m.visibility = 'public'
AND m.is_automated = 0
AND agents.is_human = 1          -- join ticket_messages.author_agent_id -> agents
```

Private notes (`visibility='private'`), automated acknowledgments
(`is_automated=1`, typically `author_kind='system'`), bots
(`agents.is_human = 0`), and agent messages on other tickets never count as
the required reply. Q4 includes tickets of **any** status.

## 4. Table catalog

Conventions: **PK** = primary key; every table lists **grain** (one row = …),
keys, and relationships. 25 tables.

### Reference / catalog

| Table | Grain | Key(s) and relationships |
|---|---|---|
| `organizations` | one row per customer organization | PK `org_id`; ← `customers.org_id` (SET NULL) |
| `customers` | one row per customer | PK `customer_id`; FK `org_id → organizations`; `email` UNIQUE; referenced by `tickets`, `ticket_messages`, `ticket_satisfaction` |
| `priorities` | one row per priority level | PK `priority_id`; `name` UNIQUE, `sort_order` UNIQUE; referenced by `tickets`, `sla_policies` |
| `channels` | one row per intake channel (email/web/phone/chat…) | PK `channel_id`; `name` UNIQUE; referenced by `tickets`, `auto_response_rules` |
| `ticket_statuses` | one row per status (`open`,`pending`,`closed`) | PK `status_code`; `counts_as_backlog` drives Q1/Q2/Q5/Q6 |
| `event_types` | one row per event type | PK `event_type`; values `created`,`status_changed`,`team_transferred`,`message`; referenced by `ticket_events` |
| `tags` | one row per tag | PK `tag_id`; `name` UNIQUE; ← `ticket_tag_map` |

### Teams & people

| Table | Grain | Key(s) and relationships |
|---|---|---|
| `teams` | one row per support team | PK `team_id`; `team_name` UNIQUE; `created_at` decides existence at a cutoff (Q2 zero rows); `archived_at` nullable (archiving ≠ deletion for snapshots) |
| `agents` | one row per human/bot support agent | PK `agent_id`; FK `team_id → teams` (RESTRICT); `is_human`, `role`; ← `ticket_messages.author_agent_id`, `agent_team_history` |
| `agent_team_history` | one row per agent×team assignment interval | PK `history_id`; FK `agent_id → agents` (CASCADE), `team_id → teams` (RESTRICT); `valid_from`/`valid_to`; disjoint intervals expected; documents agent mobility, independent of ticket ownership |

### Tickets & event backbone

| Table | Grain | Key(s) and relationships |
|---|---|---|
| `tickets` | one row per ticket | PK `ticket_id`; FK `customer_id → customers` (RESTRICT), `priority_id → priorities`, `channel_id → channels`; `created_at` = cutoff-presence test; **no status/owner columns** (derived) |
| `ticket_events` | one row per event affecting a ticket (the replay backbone) | PK `event_id`; FK `ticket_id → tickets` (CASCADE), `event_type → event_types`; `UNIQUE(ticket_id, seq)` (ordering + per-ticket sequence uniqueness), `UNIQUE(event_id, ticket_id)` (composite-FK parent) |
| `ticket_status_events` | one row per status transition (incl. creation `NULL → open`) | PK `event_id`; composite FK `(event_id, ticket_id) → ticket_events` (CASCADE); `from_status`/`to_status → ticket_statuses` (RESTRICT); CHECK `from_status <> to_status`; `reason` free text (e.g. `reopened`, `resolved`) |
| `ticket_assignment_events` | one row per ownership assignment/transfer (incl. creation `NULL → initial team`) | PK `event_id`; composite FK `(event_id, ticket_id) → ticket_events` (CASCADE); `from_team_id` nullable FK `teams`, `to_team_id NOT NULL FK teams` — **the FK probed for violations**; CHECK `from_team_id <> to_team_id`; transfer ⇒ **no** status event |
| `auto_response_rules` | one row per automated-acknowledgement rule | PK `rule_id`; `name` UNIQUE; FK `channel_id → channels` (SET NULL); referenced by `ticket_messages.auto_response_rule_id` |
| `ticket_messages` | one row per message/note/acknowledgement on a ticket | PK `event_id`; composite FK `(event_id, ticket_id) → ticket_events` (CASCADE); `author_kind ∈ {customer,agent,system}` with matching author FK columns (CHECK); `visibility ∈ {public,private}`; `is_automated 0/1`; optional `auto_response_rule_id`. Human public agent reply = `author_kind='agent' AND visibility='public' AND is_automated=0 AND agents.is_human=1`. Private notes = `visibility='private'`; automated acks = `is_automated=1` (usually `system`) |

### Auxiliary ticket data (not used by Q1–Q6, included for realism/coverage)

| Table | Grain | Key(s) and relationships |
|---|---|---|
| `sla_policies` | one row per SLA policy | PK `sla_policy_id`; `name` UNIQUE; FK `priority_id → priorities`; `respond_minutes`,`resolve_minutes > 0` |
| `ticket_sla` | one row per ticket×SLA instance | PK `ticket_sla_id`; FK `ticket_id → tickets` (CASCADE), `sla_policy_id → sla_policies` (RESTRICT); `UNIQUE(ticket_id, sla_policy_id)`; `breached` flag |
| `ticket_attachments` | one row per attached file | PK `attachment_id`; composite FK `(event_id, ticket_id) → ticket_events` (CASCADE); `uploaded_by_kind`, `size_bytes >= 0` |
| `ticket_satisfaction` | one row per CSAT response | PK `satisfaction_id`; `ticket_id` UNIQUE FK `tickets` (CASCADE); FK `customer_id → customers`; `score` 1–5 |
| `ticket_relations` | one row per directed ticket relationship | PK `relation_id`; FKs `ticket_id`,`related_ticket_id → tickets` (CASCADE); `relation_type ∈ {duplicate_of,related_to,caused_by}`; `UNIQUE(ticket_id, related_ticket_id, relation_type)`; `CHECK(ticket_id <> related_ticket_id)` |
| `ticket_tag_map` | one row per ticket×tag | PK `(ticket_id, tag_id)`; FKs → `tickets`,`tags` (both CASCADE) |

### Derived snapshot caches (rebuildable, never hand-edited)

| Table | Grain | Key(s) and relationships |
|---|---|---|
| `reporting_snapshots` | one row per snapshot run | PK `snapshot_id`; `label` UNIQUE (e.g. `march_end_2026`, `april_end_2026`); `cutoff_at` = exclusive upper bound; `built_at` |
| `snapshot_ticket_states` | one row per ticket present in a snapshot | PK `(snapshot_id, ticket_id)`; FKs → `reporting_snapshots` (CASCADE), `tickets` (CASCADE), `ticket_statuses`, `teams` (RESTRICT, `owning_team_id`), optional `last_event_id → ticket_events`; **materializes Q1-style state** |
| `snapshot_team_backlogs` | one row per team per snapshot (includes zero rows) | PK `(snapshot_id, team_id)`; FKs → `reporting_snapshots` (CASCADE), `teams` (RESTRICT); `backlog_count >= 0`; **materializes Q2/Q5-style counts** |

## 5. Frozen questions — result contract

Cutoffs: March `T3 = '2026-04-01 00:00:00'` (events `< T3`), April `T4 =
'2026-05-01 00:00:00'` (events `< T4`). All replay ties break on `seq`.
Only **Q5** is sequence-sensitive in its *result* (output ORDER BY); Q6 is
sequence-sensitive in its *replay* only.

| ID | Question (frozen) | Grain / columns | Duplicates & ordering | Zero / cutoff rules |
|---|---|---|---|---|
| Q1 | Which ticket IDs were open or pending at the end of March 31, 2026? | one row per ticket ID; `ticket_id` | DISTINCT by ticket; no ORDER BY required | Tickets created `>= T3` absent; status from replay `< T3` |
| Q2 | For every team existing at the end of March 31, 2026, return its ID and number of open or pending tickets it owned then, including zero | one row per team; `team_id, backlog_count` (ID first, integer count second) | one row per team created before `T3`, even if zero | teams with `created_at >= T3` excluded; zero-count rows **required** |
| Q3 | Which distinct ticket IDs reopened during March 2026 after a previous closure? | one row per ticket ID; `ticket_id` | `DISTINCT`; a Feb-closed ticket reopened twice in March appears **once** | Reopen event window `[2026-03-01 00:00:00, T3)`; requires `from_status='closed'` |
| Q4 | Which ticket IDs had a customer message by the end of March 31, 2026, but no subsequent public human agent reply on that ticket by then? | one row per ticket ID; `ticket_id` | one row per qualifying ticket; any status allowed | first customer message `< T3`; **no** later public, non-automated, human (`agents.is_human = 1`) agent reply on the same ticket `< T3` |
| Q5 [ordered] | Up to three team IDs and their positive backlog counts at end of March, ordered by count DESC then team ID ASC | one row per team; `team_id, backlog_count` (ID first, integer count second) | at most 3 rows; order mandatory: `backlog_count DESC, team_id ASC`; ties at place 3 vs place 4 **must be compared before `LIMIT 3`** | zero backlogs excluded from output; teams pre-`T3` only |
| Q6 | Which ticket IDs were open or pending at end of March 31, 2026, and closed at end of April 30, 2026? | one row per ticket ID; `ticket_id` | one row per qualifying ticket; no ORDER BY required | status at `< T3` ∈ {open,pending} **and** status at `< T4` = `closed`; an April reopening at the closure's timestamp with higher `seq` keeps the ticket out |

Duplicate handling: one row per qualifying entity for Q1/Q3/Q4/Q6; Q2 exactly
one row per pre-cutoff team; Q5 at most three rows.

## 6. Gold replay logic (reviewer reference, not solver material)

Status-at-cutoff CTE (used by Q1, Q2, Q5, Q6). The `COALESCE(..., 'open')`
fallback in Q6's gold form is defensive only — every present ticket has a
creation status event, so it never triggers; it is kept so a malformed world
fails loudly at validation time rather than silently dropping the row:

```sql
WITH status_at AS (
  SELECT t.ticket_id, s.to_status AS status,
         ROW_NUMBER() OVER (PARTITION BY s.ticket_id
                            ORDER BY e.occurred_at DESC, e.seq DESC) AS rn
  FROM tickets t
  JOIN ticket_status_events s ON s.ticket_id = t.ticket_id
  JOIN ticket_events e ON e.event_id = s.event_id
  WHERE e.occurred_at < :cutoff AND t.created_at < :cutoff
)
SELECT ticket_id, status FROM status_at WHERE rn = 1;
```

Owner-at-cutoff CTE is identical with `ticket_assignment_events.to_team_id`.

Q3:

```sql
SELECT DISTINCT se.ticket_id
FROM ticket_status_events se
JOIN ticket_events e
  ON e.event_id = se.event_id AND e.ticket_id = se.ticket_id
WHERE e.occurred_at >= '2026-03-01 00:00:00'
  AND e.occurred_at <  '2026-04-01 00:00:00'
  AND se.from_status = 'closed'
  AND se.to_status IN ('open','pending');
```

Q4 (checked form, includes the human-agent join):

```sql
WITH cust_msgs AS (
  SELECT e.ticket_id, e.occurred_at, e.seq,
         ROW_NUMBER() OVER (PARTITION BY e.ticket_id
                            ORDER BY e.occurred_at, e.seq) AS rn
  FROM ticket_events e
  JOIN ticket_messages m ON m.event_id = e.event_id AND m.ticket_id = e.ticket_id
  WHERE m.author_kind = 'customer'
    AND e.occurred_at < '2026-04-01 00:00:00'
),
first_cust AS (SELECT ticket_id, occurred_at, seq FROM cust_msgs WHERE rn = 1)
SELECT fc.ticket_id
FROM first_cust fc
WHERE NOT EXISTS (
  SELECT 1
  FROM ticket_events e
  JOIN ticket_messages m ON m.event_id = e.event_id AND m.ticket_id = e.ticket_id
  JOIN agents a ON a.agent_id = m.author_agent_id
  WHERE e.ticket_id = fc.ticket_id
    AND m.author_kind = 'agent'
    AND m.visibility = 'public'
    AND m.is_automated = 0
    AND a.is_human = 1
    AND e.occurred_at < '2026-04-01 00:00:00'
    AND (e.occurred_at > fc.occurred_at
         OR (e.occurred_at = fc.occurred_at AND e.seq > fc.seq))
)
ORDER BY fc.ticket_id;  -- display only; Q4 result is unordered
```

Q6: `status_at(< T3) IN ('open','pending')` AND `status_at(< T4) = 'closed'`.
Evaluating both with `ORDER BY occurred_at, seq` makes a same-timestamp
closure→reopening (closure seq *n*, reopen seq *n+1*) resolve to the reopen at
the April cutoff — the ticket does **not** qualify. The recorded fixture
(§12.1) exercises exactly this shape at `2026-04-20 10:00:00` (events
`20004`/`20005`, ticket 2002).

## 7. Fixture distinctions (from the brief's review matrix)

Each world must **distinguish** the gold answer from one plausible
same-shape alternative encoding exactly one wrong business assumption. Fixture
facts below are normative; each must occur in ≥ 1 world of its question's
assigned split. The recorded fixture exercises every one of them (§12.1).

| Q | Fixture fact / world requirement | Expected distinction (gold vs wrong alternative) |
|---|---|---|
| Q1 | A pending ticket closes **exactly at** `2026-04-01 00:00:00` (April 1); a ticket is created exactly at the cutoff | Gold: the closing ticket is still pending in March → included; the at-cutoff creation is absent. Wrong (`<=` cutoff): drops the pending ticket, admits the at-cutoff creation |
| Q2 | A ticket **transfers A → B exactly at midnight April 1**; B owns nothing in March | Gold: A gets the ticket in March, B appears with **0**. Wrong (inclusive `<=` cutoff): A loses it, B gets 1 |
| Q3 | A ticket closed in February reopens **twice** in March (two `closed→open` events), plus an April-only reopening | Gold: ID appears **once**. Wrong (no DISTINCT): ID appears twice |
| Q4 | Ticket X: customer message → private note + automated acknowledgment in March → public human reply only in April. Ticket Y: customer message → public human reply in March. Plus: agent reply *before* the first customer message, and a bot (`is_human=0`) "reply" | Gold: X included, Y excluded, pre-customer reply does not count, bot reply does not count. Wrong (drops `visibility='public'`): X drops out |
| Q5 | Teams 10, 20, 30, 40 with backlogs 6, 5, 4, 4 | Gold: `(10,6),(20,5),(30,4)`. Wrong reversed tie-break (`team_id DESC`): third row becomes `(40,4)`. The tie at count 4 between place 3 (30) and place 4 (40) must be compared **before** truncation |
| Q6 | Two March-open tickets close in April; one **reopens later in April at the same timestamp as its closure but with a higher seq** | Gold: only the still-closed ticket qualifies. Wrong ("has any April `to_status='closed'` event" without replay): includes the reopened ticket |

Q5 marker: `[ordered]`. Only Q5 carries `[ordered]` in the question ID list.
Fixture must expose the reversed sort; place 3 (`30,4`) and place 4 (`40,4`)
must be compared explicitly before `LIMIT 3` is applied.

## 8. Generation, splits, and release checks

### 8.1 Splits and questions

- Nine seeded Faker worlds: worlds 1–3 **train** (Q1, Q2, Q3), worlds 4–6
  **validation** (Q4), worlds 7–9 **test** (Q5, Q6).
- Suggested seeds: train `101/102/103`, validation `201/202/203`, test
  `301/302/303`. Record every seed in the manifest.
- Vary across seeds: ticket ID bases/ranges, team ID sets (test worlds must
  include the `10/20/30/40` backlog configuration for Q5), customer/agent pool
  sizes, event histories (reopen counts, transfer counts, message mixes),
  and backlog sizes (including exact ties at 4 vs 4 for Q5).
- Each fixture distinction in §7 must appear in ≥ 1 world **of its question's
  assigned split**. Q1's midnight close → a train world; Q2's midnight
  transfer → train; Q3's double reopen → train; Q4's X/Y pair → validation;
  Q5's 6/5/4/4 → test; Q6's same-timestamp reopen → test.
- **Q5 extra check**: in every test world, run the count query to full length,
  print place 3 and place 4, assert they differ by construction (or that the
  fixture deliberately ties them and `team_id ASC` decides), and only then
  apply `LIMIT 3`. The reversed-tie-break alternative
  (`ORDER BY backlog_count DESC, team_id DESC`) must select team 40 — record it
  as the plausible wrong query and show the fixture distinguishes them
  (done for the frozen fixture: §12.1).

### 8.2 Expected answers

- Derive expected answers **by replaying generated events in Python**
  (independent of the SQL under review), then execute all six SQL queries in
  **every world** before exporting split-specific examples. Any mismatch
  blocks export.
- Keep the golden replay implementation minimal (read events, fold by
  `(occurred_at, seq)`) and free of SQL so it cannot inherit a SQL bug.

### 8.3 Wrong-query audit

For each question, execute one plausible same-shape alternative with exactly
one incorrect assumption (§7) and record:

1. the fixture fact that distinguishes gold from alternative,
2. whether the alternative produced a different row set (must, in the world
   carrying the fixture fact),
3. the world ID(s) carrying it.

Executed for the frozen fixture — all six alternatives diverged as predicted
(§12.1). To be repeated per world at release time.

### 8.4 Broken-relationship probe

```sql
PRAGMA foreign_keys = ON;
-- pick a valid event created by an accepted generator run:
INSERT INTO ticket_assignment_events (event_id, ticket_id, from_team_id, to_team_id)
VALUES (:valid_event_id, :valid_ticket_id, NULL, 999999);
-- Expected: FOREIGN KEY constraint failed  (SQLITE_CONSTRAINT_FOREIGNKEY)
```

The probe targets `ticket_assignment_events.to_team_id → teams(team_id)`. A
passing probe is recorded in the manifest. The probes should also be exercised
in both modes: with `PRAGMA foreign_keys = ON` (expect error) and
`= OFF` (expect silent success) — the OFF outcome is recorded to document
that environment hygiene, not the schema alone, is the enforcement mechanism.
Nine probes were executed in the recorded review; all nine were rejected with
`SQLITE_CONSTRAINT_FOREIGNKEY` (§12.2), covering: the `to_team_id` path
(#1, #2, #3, #4, #7, #8), the nullable-`from_team_id` path (#9 vs #3), the
`agents` FK via a message probe (#5), and the composite-FK idiom (#6).

### 8.5 Manifest

`manifest.json` (or equivalent) records, per world and overall: seeds, split
assignment, generator version, model ID used for any repaired gold SQL,
scenario coverage matrix (which §7 fixture lives where), per-question
first-attempt pass/fail, all repairs applied with before/after diffs, wrong-query
results, FK-probe result, export file hashes, and run timestamps. Report
**first-attempt** results separately from **repaired** answers; never overwrite
first-attempt outcomes when a repair lands.

### 8.6 Separation of concerns

Solver-facing artifacts (database file, schema, solver prompts, per-split
examples) are kept **separate** from evaluator artifacts (Python replay
answers, wrong-query diffs, manifest). The evaluator must be able to delete and
rebuild solver databases without touching answers, and vice versa. Recommended
layout:

```
data/<world_id>.sqlite            # solver-facing, no answers
prompts/<world_id>.txt            # solver-facing
evaluator/answers.json            # gold answers (Python replay)
evaluator/wrong_queries.json      # alternatives + distinguishing facts
manifest.json                     # seeds, model ID, coverage, first-attempt vs repaired
```

No expected-answer table exists in `schema.sql` by design — do not add one.

## 9. Assumptions

1. A ticket's `created` event is `seq = 1`; `seq` is unique per ticket
   (generator-enforced; `UNIQUE(ticket_id, seq)` is enforced by DDL; contiguity
   is a generator property, not a DDL guarantee).
2. `tickets.created_at == created event.occurred_at` (generator invariant,
   checked in tests rather than by trigger).
3. Transfers preserve status and therefore write **no** `ticket_status_events`
   row; reopening writes `from_status='closed'` — the only source of
   `from_status='closed'` is a previous close, which is what makes Q3 sound.
4. Customers always post with `visibility='public'`; `private` is used for
   agent notes and internal system chatter.
5. Automated acknowledgments carry `is_automated=1` (typically
   `author_kind='system'`) and never satisfy Q4's reply condition, even if
   publicly visible. A bot masquerading as `author_kind='agent'` carries
   `agents.is_human = 0` and is likewise excluded.
6. "Teams existing at the cutoff" = `teams.created_at < cutoff` — **strictly
   before**. A team created exactly at `'2026-04-01 00:00:00'` is excluded from
   Q2/Q5. Archiving (`archived_at`) does not remove a team from a snapshot for
   which it existed; the team row and its (zero or non-zero) backlog still count.
7. Tickets created exactly at the cutoff are absent from that snapshot
   ("created at or after the cutoff"); their events are therefore absent too.
8. "Ownership at the cutoff" = the latest `ticket_assignment_events` with
   `occurred_at < cutoff`; never-transferred tickets keep their creation
   assignment.
9. April events may be inserted into the same tables at any time before export;
   the March snapshot stays reproducible because replay filters `occurred_at`
   and events are append-only. Backfilling corrections into the *past* requires
   rebuilding the affected snapshots (`reporting_snapshots` rows and children),
   never in-place edits.
10. Backlog size at a snapshot counts distinct tickets, each once, under exactly
    one owning team; a ticket with zero events cannot exist (creation is event 1).
11. Same-timestamp events across *different* tickets have no defined order and
    need none; seq tie-breaking is only defined within a ticket.
12. Q6's April cutoff is end of April 30 = `T4 = '2026-05-01 00:00:00'`
    (exclusive), consistent with "April snapshot includes events strictly
    before 2026-05-01 00:00:00".
13. Q5's "positive backlog counts" excludes zero rows; Q2 is the one that must
    emit zeros.
14. Agent-team history (`agent_team_history`) documents agent staffing only and
    is never consulted for ticket ownership.
15. `COALESCE(..., 'open')` fallbacks in reference SQL are defensive; in any
    well-formed world they never fire, because the creation event guarantees a
    status row before the cutoff for every present ticket.

## 10. Open questions / ambiguities

1. **Team created exactly at the cutoff**: §3 treats `created_at < cutoff` as
   "existing". If the intent is inclusive (`<=`), Q2/Q5 zero-row membership for
   teams created at precisely `2026-04-01 00:00:00` changes. Confirm before
   freezing fixtures.
2. **Customer message visibility**: may customers ever post private messages
   (shared inbox internal remarks)? If so, should Q4's anchor be restricted to
   customer messages with `visibility='public'`?
3. **Automated agent messages**: can `author_kind='agent'` ever carry
   `is_automated=1` (bot-as-agent)? Q4 excludes it today, and also excludes
   `agents.is_human = 0`; confirm both predicates are intended.
4. **Closed→closed attempts / no-op events**: DDL forbids `from_status =
   to_status`. If the generator wants an audit "touched" event, use a separate
   event type (e.g. `note`) rather than a status event.
5. **Ticket deletion/merge**: `ticket_relations ('duplicate_of')` merges
   reporting only — no reassignment of events. Confirm merges never move
   ownership across tickets.
6. **Snapshot labels**: standard labels (`march_end_2026`, `april_end_2026`)
   vs free text — affects manifest keying.
7. **Time handling source**: generator must produce whole-second UTC strings
   (no fractional seconds, no offsets like `Z` or `+00:00`) to keep `GLOB`
   checks and lexicographic replay valid. Sub-second precision would need a
   format change across DDL, fixtures, and gold SQL.
8. **Q3 wording**: "reopened during March 2026 after a previous closure" —
   gold uses `from_status='closed'` in `[2026-03-01, T3)`. A ticket closed and
   reopened *within* March qualifies once; confirm that a February close is
   not required (it is not — any prior closure satisfies "after a previous
   closure").
9. **Q4 "subsequent"**: anchored strictly after the *first* customer message
   in `(occurred_at, seq)`; a public human agent reply posted *before* any
   customer message does not count as a reply to it. Confirm.
10. **Snapshot caches in solver databases**: should solver DBs contain
    `reporting_snapshots`/`snapshot_*` at all (they leak gold shape), or only
    raw events? Recommendation: keep them, but never populate them in
    solver-facing worlds — populate only in evaluator copies.

## 11. Release checklist

- [x] `schema.sql` loads cleanly into a fresh SQLite file; all 25 tables and
      indexes created; `PRAGMA foreign_keys = ON` verified by the probe run.
- [x] Frozen fixture (single representative world) seeds the §7 distinctions;
      all six gold queries executed and returned the expected row sets.
- [x] One plausible wrong same-shape query per question executed; every one
      diverged from gold by the predicted fixture fact (§12.1).
- [x] Nine broken-relationship probes executed; all rejected with
      `SQLITE_CONSTRAINT_FOREIGNKEY` (§12.2).
- [x] Q5 third-vs-fourth-place comparison recorded: place 3 = team 30 (4),
      place 4 = team 40 (4); `team_id ASC` tie-break admits 30; the reversed
      tie-break wrongly admits 40 (§12.1).
- [ ] Seed reference rows inserted (`ticket_statuses`, `event_types`) per world.
- [ ] Nine worlds generated (3/3/3 across train/validation/test); seeds logged;
      ticket/team IDs, histories, and backlog sizes varied per seed.
- [ ] Each §7 fixture distinction present in ≥ 1 world of its split.
- [ ] All six queries execute in every world; Python-replay answers match
      (mismatch = block export, record in manifest).
- [ ] Wrong-query audit per question re-executed per world; distinguishing
      fixture fact recorded.
- [ ] FK probe re-executed per world; manifest records both `ON` (reject) and
      `OFF` (silent success) outcomes.
- [ ] March snapshot rebuilt after April events are inserted and verified
      byte-identical in *content* to the pre-April replay.
- [ ] First-attempt vs repaired results reported separately; manifest complete;
      solver artifacts and evaluator answers kept separate.

## 12. Review outcome and evidence (executed)

This revision records an **executed** review run against the frozen fixture
(fixture = recursive-CTE backlog pool tickets 1001–1019; non-pool tickets
2001–2003, 3001–3003, 4001, 5001–5002, 6001–6006; teams 10, 20, 30, 40, 50,
60, 70, 80, 90; all pool tickets created `2026-03-02`; fixture intentionally
leaves `reporting_snapshots`/`snapshot_*` unpopulated). Gold rows below were
returned by executing the gold SQL in §6 against that fixture. Wrong-query
rows were returned by executing the paired wrong query in §12.1's table —
every one diverged, as required for a discriminating fixture.

### 12.1 Gold results and wrong-query divergence (as executed)

| ID | Gold rows (executed) | Wrong query → executed result | Distinguishing fixture fact |
|---|---|---|---|
| Q1 | `[[1001],[1002],[1003],[1004],[1005],[1006],[1007],[1008],[1009],[1010],[1011],[1012],[1013],[1014],[1015],[1016],[1017],[1018],[1019],[2001],[2002],[3001],[4001]]` | `<= '2026-04-01 00:00:00'` → drops 3001, admits 3002 | Ticket 3001 (pending) closes exactly at `2026-04-01 00:00:00` in event 30003 — outside the half-open March window; ticket 3002 (event 30004) is created at exactly the cutoff and is absent from March. 3003 (closed 2026-03-31 23:59:59) is closed under both, so 3001/3002 are the discriminators |
| Q2 | `[[10,6],[20,5],[30,4],[40,4],[50,1],[60,0],[80,0],[90,3]]` | `<=` cutoff → team 50 = 0, team 60 = 1 | Ticket 4001 transfers 50→60 exactly at `2026-04-01 00:00:00` (event 40002, status preserved). March must count it under team 50 and list team 60 with **zero**. (Related: 3001 closes at the cutoff and 3002 is created at the cutoff; team 90 stays 3 under both variants — the 50/60 swap is the clean discriminator; team 70 was created 2026-04-10 and is excluded; team 80 counts zero) |
| Q3 | `[[5001]]` | same shape minus DISTINCT → `[[5001],[5001]]` | Ticket 5001: closed 2026-02-20 (event 50002), reopened 2026-03-05 (event 50003), closed 2026-03-12 (event 50004), reopened 2026-03-25 closed→pending (event 50005) — two qualifying March reopenings, one ID out. 5002's reopening (event 50009, 2026-04-05) is after the cutoff; 2002's same-timestamp April reopening (event 20005) is also after the cutoff; 5001's 2026-03-28 pending→closed (event 50006) is a close, not a reopening |
| Q4 | `[[6001],[6005],[6006]]` | drops the `visibility='public'` predicate → `[[6005],[6006]]` | Ticket 6001: customer msg 2026-03-15 (event 60002); followed only by a PRIVATE human note (event 60003, agent 1002) and a PUBLIC but AUTOMATED system ack (event 60004, is_automated=1); the public human reply (event 60006, agent 1002) lands 2026-04-05, after the cutoff → included by gold, dropped by the visibility-blind query. Ticket 6002 (public human reply 2026-03-20, event 60009) drops out of both. 6004's first customer message is 2026-04-02 → absent from both. 6005's only public human reply (event 60015, 2026-03-10) *precedes* its first customer message (event 60016, 2026-03-12) → included by both. 6006's only subsequent public reply (event 60020) is from bot agent 1004 (`is_human=0`) → included by both |
| Q5 [ordered] | `[[10,6],[20,5],[30,4]]` | reversed tie-break (`team_id DESC`) → `[[10,6],[20,5],[40,4]]` | Teams 30 and 40 both carry 4 March backlog tickets; place 3 vs place 4 at equal count 4 must be compared before `LIMIT 3`. `team_id ASC` admits 30; `DESC` admits 40. Pending pool tickets (1006/1011/1019) still count as backlog; April boundary events (30003 close, 40002 transfer, 30004 creation) are outside the March replay; team 90 = 3, team 50 = 1, teams 60/80 = 0, team 70 nonexistent — none reaches the top 3 |
| Q6 | `[[2001],[3001]]` | "any April `to_status='closed'` event exists" → `[[2001],[2002],[3001]]` | Ticket 2002 is open at the March cutoff and closes 2026-04-20 10:00:00 (event 20004, seq 2), but **reopens at the same timestamp** (event 20005, seq 3, higher sequence) → open at the April cutoff → excluded. Ticket 2001 (closed 2026-04-10 14:00, event 20002, nothing later) and ticket 3001 (pending at March cutoff; closed by the event at exactly `2026-04-01 00:00:00`, which is inside the April snapshot since only `occurred_at < '2026-05-01'` counts there) both qualify. Ticket 2003 closed before March; other pool/6xxx tickets are not closed at the April cutoff |

All six questions were executed against the fixture; each gold query returned
exactly the expected row set, and each wrong query returned the predicted
divergent row set. Q6's `(occurred_at, seq)` ordering — not `occurred_at`
alone — is load-bearing for the same-timestamp close/reopen pair.

### 12.2 Broken-relationship probes (all executed; all rejected)

Every probe was executed under `PRAGMA foreign_keys = ON` and rejected with
`SQLITE_CONSTRAINT_FOREIGNKEY`. Probe details, as recorded:

| # | Probe (abbreviated) | Violated constraint |
|---|---|---|
| 1 | `INSERT ticket_assignment_events (60005, 6001, 90, 9999)` | `to_team_id → teams(team_id)` missing (event 60005 exists; only the team is bogus) |
| 2 | `INSERT ticket_events (90001, 2001, 3, '2026-04-15 10:00:00', 'team_transferred')` then `INSERT ticket_assignment_events (90001, 2001, 90, 9999)` | `to_team_id → teams(team_id)` missing, under an otherwise valid new event |
| 3 | `INSERT ticket_assignment_events (20002, 2001, NULL, 9999)` | `to_team_id` missing; exercises the nullable `from_team_id` path |
| 4 | `INSERT ticket_assignment_events (20002, 2001, 90, 9999)` | `to_team_id → teams(team_id)` missing |
| 5 | `INSERT ticket_messages (20002, 2001, 'agent', 9999, 'public', 0, 'probe: nonexistent agent')` | `author_agent_id → agents(agent_id)` missing |
| 6 | `INSERT ticket_status_events (40002, 2001, 'open', 'closed', 'probe…')` | composite FK: `(event_id=40002, ticket_id=2001)` does not exist in `ticket_events` (40002 belongs to ticket 4001) |
| 7 | `INSERT ticket_assignment_events (60021, 6006, 90, 9999)` | `to_team_id → teams(team_id)` missing |
| 8 | `INSERT ticket_assignment_events (20002, 2001, 90, 9999)` | duplicate of #4 (repeatability) |
| 9 | `INSERT ticket_assignment_events (20004, 2002, 9999, 90)` | `from_team_id → teams(team_id)` missing (valid `to_team_id` = 90) |

A release run should additionally record each probe under
`PRAGMA foreign_keys = OFF` (expected: silent success) to document that
enforcement is a client-side pragma, not a schema property — this half is part
of the release checklist (§11) and is not covered by the probes above.

### 12.3 Explicitly not yet done at this revision

- Nine Faker worlds (3 train / 3 validation / 3 test, suggested seeds
  101/102/103, 201/202/203, 301/302/303) with the §7 distinctions placed in
  their assigned splits; varied ticket/team ID bases, event histories, and
  backlog sizes across seeds.
- Execution of the six gold queries in every world against Python-replay
  answers; per-world wrong-query audit; Q5 third/fourth-place comparison in
  each test world.
- Snapshot reproducibility check: rebuild March after April inserts and diff.
- Manifest with model ID, first-attempt vs repaired outcomes, export hashes,
  and scenario coverage matrix.

The frozen fixture demonstrates the schema, the replay contract, the question
contract, and the discrimination power of the fixture — it is the reference
case from which the nine worlds are generated and checked, not a replacement
for them.
