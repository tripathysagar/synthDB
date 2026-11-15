-- schema.sql
-- Help-desk ticketing synthetic dataset — SQLite DDL
-- Conventions:
--   * All timestamps are UTC, stored as TEXT in ISO-8601 'YYYY-MM-DD HH:MM:SS'.
--     Lexicographic ordering equals chronological ordering.
--   * Cutoffs are exclusive upper bounds. March snapshot replays events with
--     occurred_at < '2026-04-01 00:00:00'; April replays events with
--     occurred_at < '2026-05-01 00:00:00'.
--   * Replay order is (occurred_at, seq) ascending, where seq is unique
--     within a ticket.
--   * Foreign keys are declared; the client MUST run `PRAGMA foreign_keys = ON`
--     (see DOMAIN.md). SQLite does not enforce them otherwise.
--   * Detail tables use a composite FK (event_id, ticket_id) into
--     ticket_events(event_id, ticket_id) so a detail row can never disagree
--     with its event about which ticket it belongs to.
--   * statuses/event_types are seeded reference rows (DML, not in this file):
--     ticket_statuses: open=1 backlog, pending=1 backlog, closed=0 backlog.
--     event_types: 'created', 'status_changed', 'team_transferred', 'message'.

-- ---------------------------------------------------------------------------
-- Reference / catalog
-- ---------------------------------------------------------------------------

CREATE TABLE organizations (
  org_id      INTEGER PRIMARY KEY,
  org_name    TEXT NOT NULL UNIQUE,
  created_at  TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]')
);

CREATE TABLE customers (
  customer_id  INTEGER PRIMARY KEY,
  org_id       INTEGER REFERENCES organizations(org_id) ON DELETE SET NULL,
  full_name    TEXT NOT NULL,
  email        TEXT NOT NULL UNIQUE,
  created_at   TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]')
);

CREATE TABLE priorities (
  priority_id  INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  sort_order   INTEGER NOT NULL UNIQUE CHECK (sort_order >= 1)
);

CREATE TABLE channels (
  channel_id   INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE
);

CREATE TABLE ticket_statuses (
  status_code        TEXT PRIMARY KEY CHECK (status_code IN ('open', 'pending', 'closed')),
  label              TEXT NOT NULL,
  counts_as_backlog  INTEGER NOT NULL CHECK (counts_as_backlog IN (0, 1))
);

CREATE TABLE event_types (
  event_type   TEXT PRIMARY KEY,
  description  TEXT NOT NULL
);

CREATE TABLE tags (
  tag_id       INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------------
-- Teams & people
-- ---------------------------------------------------------------------------

CREATE TABLE teams (
  team_id      INTEGER PRIMARY KEY,
  team_name    TEXT NOT NULL UNIQUE,
  created_at   TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  archived_at  TEXT CHECK (archived_at IS NULL OR archived_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]')
);

CREATE TABLE agents (
  agent_id     INTEGER PRIMARY KEY,
  team_id      INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  full_name    TEXT NOT NULL,
  email        TEXT NOT NULL UNIQUE,
  is_human     INTEGER NOT NULL DEFAULT 1 CHECK (is_human IN (0, 1)),
  role         TEXT NOT NULL DEFAULT 'agent' CHECK (role IN ('agent', 'senior_agent', 'lead')),
  hired_at     TEXT NOT NULL CHECK (hired_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]')
);

CREATE TABLE agent_team_history (
  history_id   INTEGER PRIMARY KEY,
  agent_id     INTEGER NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
  team_id      INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  valid_from   TEXT NOT NULL CHECK (valid_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  valid_to     TEXT CHECK (valid_to IS NULL OR valid_to GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);

-- ---------------------------------------------------------------------------
-- Tickets & event backbone
-- ---------------------------------------------------------------------------

CREATE TABLE tickets (
  ticket_id    INTEGER PRIMARY KEY,
  customer_id  INTEGER NOT NULL REFERENCES customers(customer_id) ON DELETE RESTRICT,
  priority_id  INTEGER NOT NULL REFERENCES priorities(priority_id) ON DELETE RESTRICT,
  channel_id   INTEGER NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
  subject      TEXT NOT NULL,
  created_at   TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]')
);

CREATE TABLE ticket_events (
  event_id     INTEGER PRIMARY KEY,
  ticket_id    INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  seq          INTEGER NOT NULL CHECK (seq >= 1),
  occurred_at  TEXT NOT NULL CHECK (occurred_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  event_type   TEXT NOT NULL REFERENCES event_types(event_type) ON DELETE RESTRICT,
  UNIQUE (ticket_id, seq),
  UNIQUE (event_id, ticket_id)
);

CREATE TABLE ticket_status_events (
  event_id     INTEGER PRIMARY KEY,
  ticket_id    INTEGER NOT NULL,
  from_status  TEXT REFERENCES ticket_statuses(status_code) ON DELETE RESTRICT,
  to_status    TEXT NOT NULL REFERENCES ticket_statuses(status_code) ON DELETE RESTRICT,
  reason       TEXT,
  CHECK (from_status IS NULL OR from_status <> to_status),
  FOREIGN KEY (event_id, ticket_id) REFERENCES ticket_events(event_id, ticket_id) ON DELETE CASCADE
);

CREATE TABLE ticket_assignment_events (
  event_id     INTEGER PRIMARY KEY,
  ticket_id    INTEGER NOT NULL,
  from_team_id INTEGER REFERENCES teams(team_id) ON DELETE RESTRICT,
  to_team_id   INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  CHECK (from_team_id IS NULL OR from_team_id <> to_team_id),
  FOREIGN KEY (event_id, ticket_id) REFERENCES ticket_events(event_id, ticket_id) ON DELETE CASCADE
);

CREATE TABLE auto_response_rules (
  rule_id      INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  channel_id   INTEGER REFERENCES channels(channel_id) ON DELETE SET NULL,
  template     TEXT NOT NULL,
  is_active    INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  created_at   TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]')
);

CREATE TABLE ticket_messages (
  event_id              INTEGER PRIMARY KEY,
  ticket_id             INTEGER NOT NULL,
  author_kind           TEXT NOT NULL CHECK (author_kind IN ('customer', 'agent', 'system')),
  author_customer_id    INTEGER REFERENCES customers(customer_id) ON DELETE RESTRICT,
  author_agent_id       INTEGER REFERENCES agents(agent_id) ON DELETE RESTRICT,
  visibility            TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'private')),
  is_automated          INTEGER NOT NULL DEFAULT 0 CHECK (is_automated IN (0, 1)),
  auto_response_rule_id INTEGER REFERENCES auto_response_rules(rule_id) ON DELETE SET NULL,
  body                  TEXT NOT NULL,
  CHECK (
    (author_kind = 'customer' AND author_customer_id IS NOT NULL AND author_agent_id IS NULL) OR
    (author_kind = 'agent'    AND author_agent_id    IS NOT NULL AND author_customer_id IS NULL) OR
    (author_kind = 'system'   AND author_customer_id IS NULL     AND author_agent_id IS NULL)
  ),
  FOREIGN KEY (event_id, ticket_id) REFERENCES ticket_events(event_id, ticket_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Auxiliary ticket data
-- ---------------------------------------------------------------------------

CREATE TABLE sla_policies (
  sla_policy_id   INTEGER PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE,
  priority_id     INTEGER NOT NULL REFERENCES priorities(priority_id) ON DELETE RESTRICT,
  respond_minutes INTEGER NOT NULL CHECK (respond_minutes > 0),
  resolve_minutes INTEGER NOT NULL CHECK (resolve_minutes > 0)
);

CREATE TABLE ticket_sla (
  ticket_sla_id   INTEGER PRIMARY KEY,
  ticket_id       INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  sla_policy_id   INTEGER NOT NULL REFERENCES sla_policies(sla_policy_id) ON DELETE RESTRICT,
  started_at      TEXT NOT NULL CHECK (started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  due_at          TEXT NOT NULL CHECK (due_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  completed_at    TEXT CHECK (completed_at IS NULL OR completed_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  breached        INTEGER NOT NULL DEFAULT 0 CHECK (breached IN (0, 1)),
  UNIQUE (ticket_id, sla_policy_id),
  CHECK (due_at > started_at)
);

CREATE TABLE ticket_attachments (
  attachment_id   INTEGER PRIMARY KEY,
  event_id        INTEGER NOT NULL,
  ticket_id       INTEGER NOT NULL,
  uploaded_by_kind TEXT NOT NULL CHECK (uploaded_by_kind IN ('customer', 'agent', 'system')),
  file_name       TEXT NOT NULL,
  size_bytes      INTEGER NOT NULL CHECK (size_bytes >= 0),
  uploaded_at     TEXT NOT NULL CHECK (uploaded_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  FOREIGN KEY (event_id, ticket_id) REFERENCES ticket_events(event_id, ticket_id) ON DELETE CASCADE
);

CREATE TABLE ticket_satisfaction (
  satisfaction_id INTEGER PRIMARY KEY,
  ticket_id       INTEGER NOT NULL UNIQUE REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  customer_id     INTEGER NOT NULL REFERENCES customers(customer_id) ON DELETE RESTRICT,
  score           INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
  comment         TEXT,
  responded_at    TEXT NOT NULL CHECK (responded_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]')
);

CREATE TABLE ticket_relations (
  relation_id        INTEGER PRIMARY KEY,
  ticket_id          INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  related_ticket_id  INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  relation_type      TEXT NOT NULL CHECK (relation_type IN ('duplicate_of', 'related_to', 'caused_by')),
  UNIQUE (ticket_id, related_ticket_id, relation_type),
  CHECK (ticket_id <> related_ticket_id)
);

CREATE TABLE ticket_tag_map (
  ticket_id    INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  tag_id       INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
  PRIMARY KEY (ticket_id, tag_id)
);

-- ---------------------------------------------------------------------------
-- Derived snapshot caches (rebuilt by replaying events; never hand-edited)
-- ---------------------------------------------------------------------------

CREATE TABLE reporting_snapshots (
  snapshot_id  INTEGER PRIMARY KEY,
  label        TEXT NOT NULL UNIQUE,
  cutoff_at    TEXT NOT NULL CHECK (cutoff_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  built_at     TEXT NOT NULL CHECK (built_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
  notes        TEXT
);

CREATE TABLE snapshot_ticket_states (
  snapshot_id     INTEGER NOT NULL REFERENCES reporting_snapshots(snapshot_id) ON DELETE CASCADE,
  ticket_id       INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  status          TEXT NOT NULL REFERENCES ticket_statuses(status_code) ON DELETE RESTRICT,
  owning_team_id  INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  last_event_id   INTEGER REFERENCES ticket_events(event_id) ON DELETE SET NULL,
  PRIMARY KEY (snapshot_id, ticket_id)
);

CREATE TABLE snapshot_team_backlogs (
  snapshot_id    INTEGER NOT NULL REFERENCES reporting_snapshots(snapshot_id) ON DELETE CASCADE,
  team_id        INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
  backlog_count  INTEGER NOT NULL CHECK (backlog_count >= 0),
  PRIMARY KEY (snapshot_id, team_id)
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX idx_ticket_events_ticket_time   ON ticket_events (ticket_id, occurred_at, seq);
CREATE INDEX idx_ticket_events_time          ON ticket_events (occurred_at);
CREATE INDEX idx_ticket_events_type          ON ticket_events (event_type);
CREATE INDEX idx_status_events_to            ON ticket_status_events (to_status);
CREATE INDEX idx_status_events_from          ON ticket_status_events (from_status);
CREATE INDEX idx_assignment_to_team          ON ticket_assignment_events (to_team_id);
CREATE INDEX idx_assignment_from_team        ON ticket_assignment_events (from_team_id);
CREATE INDEX idx_messages_agent              ON ticket_messages (author_agent_id);
CREATE INDEX idx_messages_customer           ON ticket_messages (author_customer_id);
CREATE INDEX idx_messages_visibility         ON ticket_messages (visibility, is_automated);
CREATE INDEX idx_tickets_customer            ON tickets (customer_id);
CREATE INDEX idx_tickets_created             ON tickets (created_at);
CREATE INDEX idx_agents_team                 ON agents (team_id);
CREATE INDEX idx_agent_history_agent         ON agent_team_history (agent_id, valid_from);
CREATE INDEX idx_team_backlogs_team          ON snapshot_team_backlogs (team_id);
CREATE INDEX idx_ticket_states_team          ON snapshot_ticket_states (owning_team_id);
