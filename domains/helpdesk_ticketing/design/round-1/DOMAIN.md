# DOMAIN.md — Help-Desk Ticketing (Synthetic Text2SQL Dataset)

This document specifies the domain model, the replay semantics for time-cutoff
snapshots, and the review/release plan for the six frozen questions (Q1–Q6).
Schema: `schema.sql` (SQLite, 25 tables). Target questions: help-desk ticket
status, team ownership, and customer replies.

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
  every team created before the cutoff when a question requests zero counts.
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
   at the same timestamp are ordered by sequence number).
3. **Foreign keys**: SQLite does **not** enforce them by default. Every session
   must run `PRAGMA foreign_keys = ON;`. The release probe (§8.4) inserts an
   assignment referencing a nonexistent team and must observe
   `FOREIGN KEY constraint failed`.
4. **Composite FK idiom**: detail tables reference
   `ticket_events (event_id, ticket_id)`, backed by the unique index
   `UNIQUE (event_id, ticket_id)`. This makes it impossible for a status row
   to disagree with its event about the parent ticket.
5. **Creation event**: the ticket's first event (`seq = 1`, type `created`)
   carries **both** a `ticket_status_events` row (`from_status = NULL`,
   `to_status = 'open'`) and a `ticket_assignment_events` row
   (`from_team_id = NULL`, `to_team_id = <initial team>`). Both detail rows
   point at the same `event_id`. Replay therefore needs no special-cased
   initial state beyond “process events in order”.
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
- Teams “existing at cutoff” = `teams.created_at < T` (strictly before; a team
  created exactly at the cutoff is excluded — see Open Questions, §9).

**Q4 reply rule (normative)**: let `F` be the ticket's first `message` event
from `author_kind='customer'` (any visibility? — customers always write
`public`; see §9). A ticket qualifies iff `F` exists with `occurred_at < T`
and there is **no** later `message` event with `occurred_at < T` (same ticket,
strictly after `F` in `(occurred_at, seq)` order) authored by
`author_kind='agent'` with `visibility='public'` and `is_automated=0`
(`agents.is_human = 1` is the normal case; automated agents). Private notes
(`visibility='private'`), automated acknowledgments (`is_automated=1` or
`author_kind='system'`), and agent messages on other tickets never count as
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
| `ticket_messages` | one row per message/note/acknowledgement on a ticket | PK `event_id`; composite FK `(event_id, ticket_id) → ticket_events` (CASCADE); `author_kind ∈ {customer,agent,system}` with matching author FK columns (CHECK); `visibility ∈ {public,private}`; `is_automated 0/1`; optional `auto_response_rule_id`. Human public agent reply = `author_kind='agent' AND visibility='public' AND is_automated=0`. Private notes = `visibility='private'`; automated acks = `is_automated=1` (usually `system`) |

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

| ID | Question (frozen) | Grain / columns | Duplicates & ordering | Zero / cutoff rules |
|---|---|---|---|---|
| Q1 | Which ticket IDs were open or pending at the end of March 31, 2026? | one row per ticket ID; `ticket_id` | DISTINCT by ticket; no ORDER BY required | Tickets created `>= T3` absent; status from replay `< T3` |
| Q2 | For every team existing at the end of March 31, 2026, return its ID and number of open or pending tickets it owned then, including zero | one row per team; `team_id, backlog_count` | one row per team created before `T3`, even if zero | teams with `created_at >= T3` excluded; zero-count rows **required** |
| Q3 | Which distinct ticket IDs reopened during March 2026 after a previous closure? | one row per ticket ID; `ticket_id` | `DISTINCT`; a Feb-closed ticket reopened twice in March appears **once** | Reopen event window `[2026-03-01, T3)`; requires `from_status='closed'` |
| Q4 | Which ticket IDs had a customer message by the end of March 31, 2026, but no subsequent public human agent reply on that ticket by then? | one row per ticket ID; `ticket_id` | one row per qualifying ticket; any status allowed | `F` (first customer message) `< T3`; absence of a public, non-automated, agent (`author_kind='agent'`) message after `F` and `< T3` |
| Q5 | [ordered] Up to three team IDs and their positive backlog counts at end of March, ordered by count DESC then team ID ASC | one row per team; `team_id, backlog_count` | at most 3 rows; order mandatory: `backlog_count DESC, team_id ASC`; `backlog_count > 0` | zero backlogs excluded from output; verify place 3 vs place 4 **before** `LIMIT 3` |
| Q6 | Which ticket IDs were open or pending at end of March 31, 2026, and closed at end of April 30, 2026? | one row per ticket ID; `ticket_id` | one row per qualifying ticket; no ORDER BY required | status at `< T3` ∈ {open,pending} **and** status at `< T4` = `closed`; an April reopening at the closure's timestamp with higher `seq` keeps the ticket out |

Duplicate handling: one row per qualifying entity for Q1/Q3/Q4/Q6; Q2 exactly
one row per pre-cutoff team; Q5 at most three rows. Only Q5 is sequence-sensitive.

## 6. Gold replay logic (reviewer reference, not solver material)

Status-at-cutoff CTE (used by Q1, Q2, Q5, Q6):

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
Q3: `SELECT DISTINCT ticket_id FROM ticket_status_events s JOIN ticket_events e
ON e.event_id = s.event_id WHERE s.from_status = 'closed'
AND s.to_status IN ('open','pending')
AND e.occurred_at >= '2026-03-01 00:00:00' AND e.occurred_at < '2026-04-01 00:00:00';`

Q4:

```sql
WITH cust AS (
  SELECT m.ticket_id, e.occurred_at, e.seq,
         ROW_NUMBER() OVER (PARTITION BY m.ticket_id
                            ORDER BY e.occurred_at, e.seq) AS rn
  FROM ticket_messages m JOIN ticket_events e ON e.event_id = m.event_id
  WHERE m.author_kind = 'customer' AND e.occurred_at < '2026-04-01 00:00:00'
),
first_cust AS (SELECT ticket_id, occurred_at, seq FROM cust WHERE rn = 1)
SELECT f.ticket_id
FROM first_cust f
WHERE NOT EXISTS (
  SELECT 1
  FROM ticket_messages m JOIN ticket_events e ON e.event_id = m.event_id
  WHERE m.ticket_id = f.ticket_id
    AND m.author_kind = 'agent' AND m.visibility = 'public' AND m.is_automated = 0
    AND (e.occurred_at > f.occurred_at
         OR (e.occurred_at = f.occurred_at AND e.seq > f.seq))
    AND e.occurred_at < '2026-04-01 00:00:00'
);
```

Q6: `status_at(< T3) IN ('open','pending')` AND `status_at(< T4) = 'closed'`.
Evaluating both with `ORDER BY e.occurred_at, e.seq` makes a same-timestamp
closure→reopening (closure seq *n*, reopen seq *n+1*) resolve to the reopen at
the April cutoff — the ticket does **not** qualify.

## 7. Fixture distinctions (from the brief's review matrix)

Each world must **distinguish** the gold answer from one plausible
same-shape alternative encoding exactly one wrong business assumption. Fixture
facts below are normative; each must occur in ≥ 1 world of its question's
assigned split.

| Q | Fixture fact / world requirement | Expected distinction (gold vs wrong alternative) |
|---|---|---|
| Q1 | A pending ticket closes **exactly at** `2026-04-01 00:00:00` (April 1) | Gold: it is still pending in March → included. Wrong (treats March as `<= Apr 1` or uses status-at-computation-date): drops it. The midnight event is outside the March window and belongs to April only |
| Q2 | A ticket **transfers A → B exactly at midnight April 1**; B owns nothing in March | Gold: A gets the ticket in March, B appears with **0**. Wrong (applies full-history ownership, or `<=` cutoff, or omits zero rows, or inner-joins backlogs): A loses it / B absent / B missing zero row |
| Q3 | A ticket closed in February reopens **twice** in March (two `closed→open` events) | Gold: ID appears **once**. Wrong (`SELECT ticket_id` without DISTINCT): ID appears twice |
| Q4 | Ticket X: customer message → private note + automated acknowledgment in March → public human reply in April. Ticket Y: customer message → public human reply in March | Gold: X included, Y excluded. Wrong (counts notes/acks as replies, or any agent message regardless of visibility/automation): X drops out; wrong (ignores order) may qualify Y when the reply precedes the first customer message |
| Q5 | Teams 10, 20, 30, 40 with backlogs 6, 5, 4, 4 | Gold: `(10,6),(20,5),(30,4)`. Wrong reversed tie-break (`team_id DESC`, or LIMIT before sorting): selects 40 over 30. Reversing the ID tie-break selects team 40 — the check must compare 3rd vs 4th place **before** truncation |
| Q6 | Two March-open tickets close in April; one **reopens later in April at the same timestamp as its closure but with a higher seq** | Gold: only the still-closed ticket qualifies. Wrong (orders by `occurred_at` without `seq`, or treats “close in April” as sufficient): includes the reopened ticket |

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
  assigned split**. Q1's midnight-midnight close → a train world; Q2's
  midnight transfer → train; Q3's double reopen → train; Q4's
  X/Y pair → validation; Q5's 6/5/4/4 → test; Q6's same-timestamp reopen → test.
- **Q5 extra check**: in every test world, run the count query to full length,
  print place 3 and place 4, assert they differ by construction (or that the
  fixture deliberately ties them and `team_id ASC` decides), and only then apply
  `LIMIT 3`. The reversed-tie-break alternative
  (`ORDER BY backlog_count DESC, team_id DESC`) must select team 40 — record it
  as the plausible wrong query and show the fixture distinguishes them.

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

### 8.4 Broken-relationship probe

```sql
PRAGMA foreign_keys = ON;
-- pick a valid event created by an accepted generator run:
INSERT INTO ticket_assignment_events (event_id, ticket_id, from_team_id, to_team_id)
VALUES (:valid_event_id, :valid_ticket_id, NULL, 999999);
-- Expected: FOREIGN KEY constraint failed  (exit non-zero / sqlite3 error)
```
The probe targets `ticket_assignment_events.to_team_id → teams(team_id)`. A
passing probe is recorded in the manifest. Also record that with
`PRAGMA foreign_keys = OFF` the insert silently succeeds — environment hygiene
is part of the release gate, not a schema property.

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

1. A ticket's `created` event is `seq = 1`; `seq` is contiguous and unique per
   ticket (generator-enforced; `UNIQUE(ticket_id, seq)` is enforced by DDL).
2. `tickets.created_at == created event.occurred_at` (generator invariant,
   checked in tests rather than by trigger).
3. Transfers preserve status and therefore write **no** `ticket_status_events`
   row; reopening writes `from_status='closed'` — the only source of
   `from_status='closed'` is a previous close, which is what makes Q3 sound.
4. Customers always post with `visibility='public'`; `private` is used for
   agent notes and internal system chatter.
5. Automated acknowledgments carry `is_automated=1` (typically
   `author_kind='system'`) and never satisfy Q4's reply condition, even if
   publicly visible.
6. "Teams existing at the cutoff" = `teams.created_at < cutoff` — **strictly
   before**. A team created exactly at `'2026-04-01 00:00:00'` is excluded from
   Q2/Q5. Archiving (`archived_at`) does not remove a team from a snapshot for
   which it existed; the team row and its (zero or non-zero) backlog still count.
7. Tickets created exactly at the cutoff are absent from that snapshot
   ("created at or after the cutoff"); their events are therefore absent too.
8. "Ownership at the cutoff" = the latest `ticket_assignment_events` with
   `occurred_at < cutoff`; unresolved/never-transferred tickets keep their
   creation assignment.
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

## 10. Open questions / ambiguities

1. **Team created exactly at the cutoff**: §3 treats `created_at < cutoff` as
   "existing". If the intent is inclusive (`<=`), Q2/Q5 zero-row membership for
   teams created at precisely `2026-04-01 00:00:00` changes. Confirm before
   freezing fixtures.
2. **Customer message visibility**: may customers ever post private messages
   (shared inbox internal remarks)? If so, should Q4's anchor be restricted to
   customer messages with `visibility='public'`?
3. **Automated agent messages**: can `author_kind='agent'` ever carry
   `is_automated=1` (bot-as-agent)? Q4 excludes it today; confirm.
4. **Closed→closed attempts / no-op events**: DDL forbids `from_status =
   to_status`. If the generator wants an audit "touched" event, use a separate
   event type (`note`) rather than a status event.
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
9. **Q4 “subsequent”**: anchored strictly after the *first* customer message
   in `(occurred_at, seq)`; a public human agent reply posted *before* any
   customer message does not count as a reply to it. Confirm.
10. **Snapshot caches in solver databases**: should solver DBs contain
    `reporting_snapshots`/`snapshot_*` at all (they leak gold shape), or only
    raw events? Recommendation: keep them, but never populate them in
    solver-facing worlds — populate only in evaluator copies.

## 11. Release checklist

- [ ] `schema.sql` loads cleanly into a fresh SQLite file; all 25 tables and
      indexes created; `PRAGMA foreign_keys = ON` verified.
- [ ] Seed reference rows inserted (`ticket_statuses`, `event_types`).
- [ ] Nine worlds generated (3/3/3 across train/validation/test); seeds logged.
- [ ] All six queries execute in every world; Python-replay answers match
      (mismatch = block export, record in manifest).
- [ ] Each §7 fixture distinction present in ≥ 1 world of its split; Q5
      3rd-vs-4th-place comparison logged before `LIMIT 3`.
- [ ] Wrong-query audit per question executed; distinguishing fixture fact
      recorded.
- [ ] FK probe rejected (`FOREIGN KEY constraint failed`) and recorded.
- [ ] First-attempt vs repaired results reported separately; manifest complete;
      solver artifacts and evaluator answers kept separate.
- [ ] March snapshot rebuilt after April events are inserted and verified
      byte-identical in *content* to the pre-April replay.
