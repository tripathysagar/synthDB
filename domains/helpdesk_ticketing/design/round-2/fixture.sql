-- fixture.sql — Help-desk ticketing synthetic fixture (load AFTER schema.sql)
-- Timestamps UTC, ISO-8601 'YYYY-MM-DD HH:MM:SS' (lexicographic == chronological).
-- Cutoffs (exclusive upper bound): March snapshot = occurred_at < '2026-04-01 00:00:00';
--                                April snapshot = occurred_at < '2026-05-01 00:00:00'.
-- Replay order: (occurred_at, seq) ascending; seq unique within ticket.
-- PRAGMA foreign_keys = ON;  -- must be set by the client/loader (SQLite does not enforce FKs otherwise)
--
-- Fixture map (brief's review/release facts). No answer queries are included on purpose.
--   Q1  3001: pending at March cutoff; pending->closed EXACTLY 2026-04-01 00:00:00 -> belongs to March snapshot.
--       3002: created EXACTLY 2026-04-01 00:00:00 -> absent from March (created at/after cutoff).
--       3003: created exactly 2026-03-01 00:00:00 (March lower bound is INCLUSIVE); closed 2026-03-31 23:59:59 -> not open at cutoff.
--   Q2  4001: team_transferred 50 -> 60 EXACTLY 2026-04-01 00:00:00 (status preserved) -> March owns team 50; team 60 gets ZERO row in March.
--       70: team created 2026-04-10 -> does NOT exist at March cutoff (excluded from March; present in April).
--       80: team never given a ticket -> zero backlog row in March.
--   Q3  5001: closed 2026-02-20, reopened 2026-03-05, closed 2026-03-12, reopened 2026-03-25 (TWICE in March) -> ID appears ONCE.
--       5002: closed 2026-03-10, reopened 2026-04-05 (in April, not March) -> excluded.
--   Q4  6001: customer msg + PRIVATE note + AUTOMATED ack in March; PUBLIC HUMAN reply only 2026-04-05 -> INCLUDE.
--       6002: public human agent reply 2026-03-20 -> drop out.
--       6005: human agent reply 2026-03-10 PRECEDES first customer message (2026-03-12) -> not a qualifying reply -> INCLUDE.
--       6006: only a public reply from is_human=0 bot agent -> not human -> INCLUDE.
--       6004: first customer message 2026-04-02 -> no customer message by end of March -> exclude.
--   Q5  Backlog pool tickets 1001-1019 (recursive CTE): team 10 = 6 (1001-1006), team 20 = 5 (1007-1011),
--       team 30 = 4 (1012-1015), team 40 = 4 (1016-1019, pending 1019 -> tie broken by team_id ASC -> 30 wins, not 40).
--       Other March backlog: 50 -> 1 (4001), 90 -> 3 (2001, 2002, 3001); 60 = 0, 80 = 0; team 70 absent. None enters top 3.
--       1006/1011/1019 are the pending members of the pool (pending counts as backlog).
--   Q6  2001: open at March cutoff; closed 2026-04-10 14:00:00; still closed at April cutoff -> qualifies.
--       2002: open at March cutoff; closed EXACTLY 2026-04-20 10:00:00 (seq 2) and reopened SAME timestamp (seq 3, higher)
--             -> open at April cutoff -> does NOT qualify.
--       3001: pending at March cutoff; closed at April 1 midnight; closed at April cutoff -> qualifies.
--       2003: closed 2026-02-15 -> not open at March cutoff -> does NOT qualify.
-- March backlog sanity at cutoff: 10=6, 20=5, 30=4, 40=4, 50=1, 60=0, 80=0, 90=3 (70 nonexistent).
-- reporting_snapshots / snapshot_ticket_states / snapshot_team_backlogs intentionally NOT populated
-- (derived caches; rebuilt by replaying events, never hand-edited).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Reference / catalog
-- ---------------------------------------------------------------------------
INSERT INTO ticket_statuses (status_code, label, counts_as_backlog) VALUES
  ('open',    'Open',    1),
  ('pending', 'Pending', 1),
  ('closed',  'Closed',  0);

INSERT INTO event_types (event_type, description) VALUES
  ('created',          'Ticket created'),
  ('status_changed',   'Ticket status transition'),
  ('team_transferred', 'Owning team changed, status preserved'),
  ('message',          'Message on the ticket');

INSERT INTO priorities (priority_id, name, sort_order) VALUES
  (1, 'high',   1),
  (2, 'normal', 2),
  (3, 'low',    3);

INSERT INTO channels (channel_id, name) VALUES
  (1, 'email'),
  (2, 'portal'),
  (3, 'phone');

INSERT INTO organizations (org_id, org_name, created_at) VALUES
  (1, 'Org One', '2026-01-01 00:00:00'),
  (2, 'Org Two', '2026-01-01 00:00:00');

INSERT INTO customers (customer_id, org_id, full_name, email, created_at) VALUES
  (1, 1, 'Cust One',  'cust1@example.com', '2026-01-05 00:00:00'),
  (2, 1, 'Cust Two',  'cust2@example.com', '2026-01-06 00:00:00'),
  (3, 2, 'Cust Three','cust3@example.com', '2026-01-07 00:00:00');

INSERT INTO tags (tag_id, name) VALUES
  (1, 'billing'),
  (2, 'bug');

-- ---------------------------------------------------------------------------
-- Teams & people
-- ---------------------------------------------------------------------------
INSERT INTO teams (team_id, team_name, created_at, archived_at) VALUES
  (10, 'Team Alpha',           '2026-01-15 00:00:00', NULL),
  (20, 'Team Beta',            '2026-01-15 00:00:00', NULL),
  (30, 'Team Gamma',           '2026-01-15 00:00:00', NULL),
  (40, 'Team Delta',           '2026-01-15 00:00:00', NULL),
  (50, 'Team Transfer Source', '2026-01-15 00:00:00', NULL),
  (60, 'Team Transfer Target', '2026-01-15 00:00:00', NULL),
  (70, 'Team April Only',      '2026-04-10 00:00:00', NULL),
  (80, 'Team Empty',           '2026-02-01 00:00:00', NULL),
  (90, 'Team Misc',            '2026-01-15 00:00:00', NULL);

INSERT INTO agents (agent_id, team_id, full_name, email, is_human, role, hired_at) VALUES
  (1001, 10, 'Ada Human',  'ada.human@example.com',  1, 'agent',        '2026-01-10 00:00:00'),
  (1002, 20, 'Ben Human',  'ben.human@example.com',  1, 'senior_agent', '2026-01-10 00:00:00'),
  (1003, 90, 'Cid Human',  'cid.human@example.com',  1, 'lead',         '2026-01-10 00:00:00'),
  (1004, 90, 'Bot Account','bot@example.com',        0, 'agent',        '2026-01-10 00:00:00');

INSERT INTO agent_team_history (history_id, agent_id, team_id, valid_from, valid_to) VALUES
  (1, 1001, 10, '2026-01-10 00:00:00', NULL),
  (2, 1002, 20, '2026-01-10 00:00:00', NULL),
  (3, 1004, 90, '2026-01-10 00:00:00', NULL);

INSERT INTO auto_response_rules (rule_id, name, channel_id, template, is_active, created_at) VALUES
  (1, 'auto-ack-email', 1, 'Thanks, we received your ticket and will respond soon.', 1, '2026-01-01 00:00:00');

-- ---------------------------------------------------------------------------
-- Q5 backlog pool: tickets 1001..1019 via recursive CTE
--   1001-1006 -> team 10 (6) | 1007-1011 -> team 20 (5) | 1012-1015 -> team 30 (4) | 1016-1019 -> team 40 (4)
-- ---------------------------------------------------------------------------
WITH RECURSIVE pool(n) AS (
  SELECT 1
  UNION ALL SELECT n + 1 FROM pool WHERE n < 19
)
INSERT INTO tickets (ticket_id, customer_id, priority_id, channel_id, subject, created_at)
SELECT 1000 + n,
       1 + (n % 3),
       1 + (n % 3),
       1 + (n % 3),
       'Pool ticket ' || n,
       strftime('%Y-%m-%d %H:%M:%S', '2026-03-02 09:00:00', printf('+%d minutes', n * 13))
FROM pool;

WITH RECURSIVE pool(n) AS (
  SELECT 1
  UNION ALL SELECT n + 1 FROM pool WHERE n < 19
)
INSERT INTO ticket_events (event_id, ticket_id, seq, occurred_at, event_type)
SELECT 10000 + n,
       1000 + n,
       1,
       strftime('%Y-%m-%d %H:%M:%S', '2026-03-02 09:00:00', printf('+%d minutes', n * 13)),
       'created'
FROM pool;

WITH RECURSIVE pool(n) AS (
  SELECT 1
  UNION ALL SELECT n + 1 FROM pool WHERE n < 19
)
INSERT INTO ticket_status_events (event_id, ticket_id, from_status, to_status, reason)
SELECT 10000 + n, 1000 + n, NULL, 'open', 'created'
FROM pool;

WITH RECURSIVE pool(n) AS (
  SELECT 1
  UNION ALL SELECT n + 1 FROM pool WHERE n < 19
)
INSERT INTO ticket_assignment_events (event_id, ticket_id, from_team_id, to_team_id)
SELECT 10000 + n,
       1000 + n,
       NULL,
       CASE WHEN n <= 6 THEN 10 WHEN n <= 11 THEN 20 WHEN n <= 15 THEN 30 ELSE 40 END
FROM pool;

-- Pending demotions inside the pool (pending still counts as backlog)
INSERT INTO ticket_events (event_id, ticket_id, seq, occurred_at, event_type) VALUES
  (10020, 1006, 2, '2026-03-20 09:00:00', 'status_changed'),
  (10021, 1011, 2, '2026-03-21 09:00:00', 'status_changed'),
  (10022, 1019, 2, '2026-03-22 09:00:00', 'status_changed');
INSERT INTO ticket_status_events (event_id, ticket_id, from_status, to_status, reason) VALUES
  (10020, 1006, 'open', 'pending', 'awaiting_customer'),
  (10021, 1011, 'open', 'pending', 'awaiting_customer'),
  (10022, 1019, 'open', 'pending', 'awaiting_customer');

-- ---------------------------------------------------------------------------
-- Non-pool tickets (Q1/Q2/Q3/Q4/Q6 fixtures). All attach to team 90 except 4001 (team 50).
-- ---------------------------------------------------------------------------
INSERT INTO tickets (ticket_id, customer_id, priority_id, channel_id, subject, created_at) VALUES
  (2001, 1, 1, 1, 'Q6 alpha - March open, April close', '2026-03-05 10:00:00'),
  (2002, 2, 2, 2, 'Q6 beta  - close+reopen same timestamp', '2026-03-06 11:00:00'),
  (2003, 1, 3, 1, 'Q6 gamma - closed before March',     '2026-02-01 08:00:00'),
  (3001, 2, 2, 2, 'Q1 pending, closes at Apr 1 cutoff', '2026-03-03 09:30:00'),
  (3002, 3, 2, 3, 'Q1 created exactly at Apr 1 cutoff', '2026-04-01 00:00:00'),
  (3003, 1, 2, 1, 'Closed 2026-03-31 23:59:59',         '2026-03-01 00:00:00'),
  (4001, 2, 2, 2, 'Q2 transfer at Apr 1 cutoff',        '2026-03-04 12:00:00'),
  (5001, 3, 1, 2, 'Q3 closed Feb, reopened twice Mar',  '2026-02-10 09:00:00'),
  (5002, 1, 2, 3, 'Q3 reopen only in April',            '2026-03-01 09:00:00'),
  (6001, 1, 2, 1, 'Q4 private note + auto ack only',    '2026-03-01 10:00:00'),
  (6002, 2, 2, 1, 'Q4 public human reply in March',     '2026-03-02 10:00:00'),
  (6004, 3, 3, 3, 'Q4 first customer msg in April',     '2026-03-10 10:00:00'),
  (6005, 2, 2, 2, 'Q4 agent reply precedes customer',   '2026-03-08 10:00:00'),
  (6006, 1, 1, 1, 'Q4 bot reply is not human',          '2026-03-09 10:00:00');

INSERT INTO ticket_events (event_id, ticket_id, seq, occurred_at, event_type) VALUES
  (20001, 2001, 1, '2026-03-05 10:00:00', 'created'),
  (20002, 2001, 2, '2026-04-10 14:00:00', 'status_changed'),
  (20003, 2002, 1, '2026-03-06 11:00:00', 'created'),
  (20004, 2002, 2, '2026-04-20 10:00:00', 'status_changed'),
  (20005, 2002, 3, '2026-04-20 10:00:00', 'status_changed'),
  (20006, 2003, 1, '2026-02-01 08:00:00', 'created'),
  (20007, 2003, 2, '2026-02-15 09:00:00', 'status_changed'),
  (30001, 3001, 1, '2026-03-03 09:30:00', 'created'),
  (30002, 3001, 2, '2026-03-10 09:30:00', 'status_changed'),
  (30003, 3001, 3, '2026-04-01 00:00:00', 'status_changed'),
  (30004, 3002, 1, '2026-04-01 00:00:00', 'created'),
  (30005, 3003, 1, '2026-03-01 00:00:00', 'created'),
  (30006, 3003, 2, '2026-03-31 23:59:59', 'status_changed'),
  (40001, 4001, 1, '2026-03-04 12:00:00', 'created'),
  (40002, 4001, 2, '2026-04-01 00:00:00', 'team_transferred'),
  (50001, 5001, 1, '2026-02-10 09:00:00', 'created'),
  (50002, 5001, 2, '2026-02-20 10:00:00', 'status_changed'),
  (50003, 5001, 3, '2026-03-05 10:00:00', 'status_changed'),
  (50004, 5001, 4, '2026-03-12 10:00:00', 'status_changed'),
  (50005, 5001, 5, '2026-03-25 10:00:00', 'status_changed'),
  (50006, 5001, 6, '2026-03-28 10:00:00', 'status_changed'),
  (50007, 5002, 1, '2026-03-01 09:00:00', 'created'),
  (50008, 5002, 2, '2026-03-10 10:00:00', 'status_changed'),
  (50009, 5002, 3, '2026-04-05 10:00:00', 'status_changed'),
  (60001, 6001, 1, '2026-03-01 10:00:00', 'created'),
  (60002, 6001, 2, '2026-03-15 10:00:00', 'message'),
  (60003, 6001, 3, '2026-03-16 09:00:00', 'message'),
  (60004, 6001, 4, '2026-03-16 09:05:00', 'message'),
  (60005, 6001, 5, '2026-03-17 10:00:00', 'status_changed'),
  (60006, 6001, 6, '2026-04-05 10:00:00', 'message'),
  (60007, 6002, 1, '2026-03-02 10:00:00', 'created'),
  (60008, 6002, 2, '2026-03-15 11:00:00', 'message'),
  (60009, 6002, 3, '2026-03-20 10:00:00', 'message'),
  (60010, 6002, 4, '2026-03-21 10:00:00', 'status_changed'),
  (60011, 6004, 1, '2026-03-10 10:00:00', 'created'),
  (60012, 6004, 2, '2026-03-11 10:00:00', 'status_changed'),
  (60013, 6004, 3, '2026-04-02 10:00:00', 'message'),
  (60014, 6005, 1, '2026-03-08 10:00:00', 'created'),
  (60015, 6005, 2, '2026-03-10 10:00:00', 'message'),
  (60016, 6005, 3, '2026-03-12 10:00:00', 'message'),
  (60017, 6005, 4, '2026-03-13 10:00:00', 'status_changed'),
  (60018, 6006, 1, '2026-03-09 10:00:00', 'created'),
  (60019, 6006, 2, '2026-03-14 10:00:00', 'message'),
  (60020, 6006, 3, '2026-03-15 10:00:00', 'message'),
  (60021, 6006, 4, '2026-03-16 10:00:00', 'status_changed');

-- Created events: NULL -> 'open' for every ticket, and initial ownership (team 90, except 4001 -> 50)
INSERT INTO ticket_status_events (event_id, ticket_id, from_status, to_status, reason) VALUES
  (20001, 2001, NULL, 'open', 'created'),
  (20003, 2002, NULL, 'open', 'created'),
  (20006, 2003, NULL, 'open', 'created'),
  (30001, 3001, NULL, 'open', 'created'),
  (30004, 3002, NULL, 'open', 'created'),
  (30005, 3003, NULL, 'open', 'created'),
  (40001, 4001, NULL, 'open', 'created'),
  (50001, 5001, NULL, 'open', 'created'),
  (50007, 5002, NULL, 'open', 'created'),
  (60001, 6001, NULL, 'open', 'created'),
  (60007, 6002, NULL, 'open', 'created'),
  (60011, 6004, NULL, 'open', 'created'),
  (60014, 6005, NULL, 'open', 'created'),
  (60018, 6006, NULL, 'open', 'created');

INSERT INTO ticket_assignment_events (event_id, ticket_id, from_team_id, to_team_id) VALUES
  (20001, 2001, NULL, 90),
  (20003, 2002, NULL, 90),
  (20006, 2003, NULL, 90),
  (30001, 3001, NULL, 90),
  (30004, 3002, NULL, 90),
  (30005, 3003, NULL, 90),
  (40001, 4001, NULL, 50),
  (50001, 5001, NULL, 90),
  (50007, 5002, NULL, 90),
  (60001, 6001, NULL, 90),
  (60007, 6002, NULL, 90),
  (60011, 6004, NULL, 90),
  (60014, 6005, NULL, 90),
  (60018, 6006, NULL, 90),
  (40002, 4001, 50,   60);

-- Status transitions (excluding the pool and the 'created' NULL->open rows above)
INSERT INTO ticket_status_events (event_id, ticket_id, from_status, to_status, reason) VALUES
  (20002, 2001, 'open',    'closed',  'resolved'),
  (20004, 2002, 'open',    'closed',  'resolved'),
  (20005, 2002, 'closed',  'open',    'reopened_by_customer'),
  (20007, 2003, 'open',    'closed',  'resolved'),
  (30002, 3001, 'open',    'pending', 'awaiting_customer'),
  (30003, 3001, 'pending', 'closed',  'resolved'),
  (30006, 3003, 'open',    'closed',  'resolved'),
  (50002, 5001, 'open',    'closed',  'resolved'),
  (50003, 5001, 'closed',  'open',    'reopened_by_customer'),
  (50004, 5001, 'open',    'closed',  'resolved'),
  (50005, 5001, 'closed',  'pending', 'reopened_by_customer'),
  (50006, 5001, 'pending', 'closed',  'resolved'),
  (50008, 5002, 'open',    'closed',  'resolved'),
  (50009, 5002, 'closed',  'open',    'reopened_by_customer'),
  (60005, 6001, 'open',    'closed',  'resolved'),
  (60010, 6002, 'open',    'closed',  'resolved'),
  (60012, 6004, 'open',    'closed',  'resolved'),
  (60017, 6005, 'open',    'closed',  'resolved'),
  (60021, 6006, 'open',    'closed',  'resolved');

-- ---------------------------------------------------------------------------
-- Messages: Q4 discrimination cases (6001, 6002, 6004, 6005, 6006)
-- ---------------------------------------------------------------------------
INSERT INTO ticket_messages (event_id, ticket_id, author_kind, author_customer_id, author_agent_id, visibility, is_automated, auto_response_rule_id, body) VALUES
  (60002, 6001, 'customer', 1,    NULL, 'public',  0, NULL, 'Customer: VPN keeps dropping'),
  (60003, 6001, 'agent',    NULL, 1002, 'private', 0, NULL, 'Private note: escalate to network team'),
  (60004, 6001, 'system',   NULL, NULL, 'public',  1, 1,    'Automated acknowledgement'),
  (60006, 6001, 'agent',    NULL, 1002, 'public',  0, NULL, 'Public human reply after the March cutoff'),
  (60008, 6002, 'customer', 2,    NULL, 'public',  0, NULL, 'Customer: cannot log in'),
  (60009, 6002, 'agent',    NULL, 1002, 'public',  0, NULL, 'Public human reply inside March'),
  (60013, 6004, 'customer', 3,    NULL, 'public',  0, NULL, 'Customer: first message lands in April'),
  (60015, 6005, 'agent',    NULL, 1003, 'public',  0, NULL, 'Outbound human reply before customer wrote'),
  (60016, 6005, 'customer', 2,    NULL, 'public',  0, NULL, 'Customer: report is slow'),
  (60019, 6006, 'customer', 1,    NULL, 'public',  0, NULL, 'Customer: billing question'),
  (60020, 6006, 'agent',    NULL, 1004, 'public',  0, NULL, 'Bot page: we are investigating');

-- ---------------------------------------------------------------------------
-- Auxiliary coverage (not required by Q1-Q6; composite FKs + realism)
-- ---------------------------------------------------------------------------
INSERT INTO sla_policies (sla_policy_id, name, priority_id, respond_minutes, resolve_minutes) VALUES
  (1, 'high-priority-sla', 1, 30, 240);

INSERT INTO ticket_sla (ticket_sla_id, ticket_id, sla_policy_id, started_at, due_at, completed_at, breached) VALUES
  (1, 2001, 1, '2026-03-05 10:00:00', '2026-03-05 14:00:00', NULL, 0);

INSERT INTO ticket_attachments (attachment_id, event_id, ticket_id, uploaded_by_kind, file_name, size_bytes, uploaded_at) VALUES
  (1, 60008, 6002, 'customer', 'screenshot.png', 20480, '2026-03-15 11:05:00');

INSERT INTO ticket_satisfaction (satisfaction_id, ticket_id, customer_id, score, comment, responded_at) VALUES
  (1, 6002, 2, 5, 'Fast fix, thanks', '2026-03-22 09:00:00');

INSERT INTO ticket_relations (relation_id, ticket_id, related_ticket_id, relation_type) VALUES
  (1, 2002, 2001, 'related_to');

INSERT INTO ticket_tag_map (ticket_id, tag_id) VALUES
  (1001, 1),
  (1012, 2),
  (2002, 2);
