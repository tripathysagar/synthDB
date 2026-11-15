"""Seeded synthetic helpdesk worlds with an event-replay answer oracle."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import random
import sqlite3
from pathlib import Path

from faker import Faker

MARCH = "2026-04-01 00:00:00"
APRIL = "2026-05-01 00:00:00"
MARCH_START = "2026-03-01 00:00:00"


def _last_state(db: sqlite3.Connection, cutoff: str):
    tickets = {r[0]: r[1] for r in db.execute("SELECT ticket_id, created_at FROM tickets")}
    states = {}
    events = db.execute(
        "SELECT event_id,ticket_id,seq,occurred_at,event_type FROM ticket_events "
        "WHERE occurred_at < ? ORDER BY ticket_id,occurred_at,seq", (cutoff,)
    ).fetchall()
    for eid, tid, seq, at, kind in events:
        if tid not in tickets or tickets[tid] >= cutoff:
            continue
        if tid not in states:
            states[tid] = {"status": None, "team": None, "last_event_id": None}
        state = states[tid]
        if kind in ("created", "status_changed"):
            row = db.execute("SELECT to_status FROM ticket_status_events WHERE event_id=?", (eid,)).fetchone()
            if row:
                state["status"] = row[0]
        if kind in ("created", "team_transferred"):
            row = db.execute("SELECT to_team_id FROM ticket_assignment_events WHERE event_id=?", (eid,)).fetchone()
            if row:
                state["team"] = row[0]
        state["last_event_id"] = eid
    return states


def derive_answers(db: sqlite3.Connection):
    """Calculate Q1..Q6 from persisted events, without evaluating their SQL."""
    march = _last_state(db, MARCH)
    april = _last_state(db, APRIL)
    q1 = sorted((tid,) for tid, s in march.items() if s["status"] in ("open", "pending"))
    teams = [r[0] for r in db.execute("SELECT team_id FROM teams WHERE created_at < ?", (MARCH,))]
    backlog = defaultdict(int)
    for s in march.values():
        if s["status"] in ("open", "pending"):
            backlog[s["team"]] += 1
    q2 = [(team, backlog[team]) for team in sorted(teams)]
    q3 = sorted({(tid,) for tid, eid, at in db.execute(
        "SELECT s.ticket_id,s.event_id,e.occurred_at FROM ticket_status_events s "
        "JOIN ticket_events e ON e.event_id=s.event_id AND e.ticket_id=s.ticket_id "
        "WHERE e.occurred_at>=? AND e.occurred_at<? AND s.from_status='closed' "
        "AND s.to_status IN ('open','pending')", (MARCH_START, MARCH))})
    human_agents = {r[0] for r in db.execute("SELECT agent_id FROM agents WHERE is_human=1")}
    messages = db.execute(
        "SELECT m.ticket_id,m.author_kind,m.author_agent_id,m.visibility,m.is_automated,e.occurred_at,e.seq "
        "FROM ticket_messages m JOIN ticket_events e ON e.event_id=m.event_id "
        "WHERE e.occurred_at<? ORDER BY m.ticket_id,e.occurred_at,e.seq", (MARCH,)
    ).fetchall()
    by_ticket = defaultdict(list)
    for row in messages:
        by_ticket[row[0]].append(row)
    q4 = []
    for tid, rows in by_ticket.items():
        customers = [r for r in rows if r[1] == "customer"]
        if not customers:
            continue
        first = customers[0]
        replied = any(r[1] == "agent" and r[2] in human_agents and r[3] == "public" and not r[4]
                      and (r[5], r[6]) > (first[5], first[6]) for r in rows)
        if not replied:
            q4.append((tid,))
    q4.sort()
    q5 = sorted(((team, n) for team, n in backlog.items() if n > 0), key=lambda x: (-x[1], x[0]))[:3]
    q6 = sorted((tid,) for tid, s in march.items()
                if s["status"] in ("open", "pending")
                and tid in april and april[tid]["status"] == "closed")
    return {"Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4, "Q5": q5, "Q6": q6}


def rebuild_snapshots(db: sqlite3.Connection):
    """Rebuild both derived cache snapshots entirely from persisted events."""
    db.execute("DELETE FROM snapshot_team_backlogs")
    db.execute("DELETE FROM snapshot_ticket_states")
    db.execute("DELETE FROM reporting_snapshots")
    for sid, label, cutoff in ((1, "march_end_2026", MARCH), (2, "april_end_2026", APRIL)):
        db.execute("INSERT INTO reporting_snapshots VALUES (?,?,?,?,?)",
                   (sid, label, cutoff, "2026-05-01 00:00:00", "Replayed from immutable ticket events"))
        states = _last_state(db, cutoff)
        for tid, s in sorted(states.items()):
            db.execute("INSERT INTO snapshot_ticket_states VALUES (?,?,?,?,?)",
                       (sid, tid, s["status"], s["team"], s["last_event_id"]))
        counts = defaultdict(int)
        for s in states.values():
            if s["status"] in ("open", "pending"):
                counts[s["team"]] += 1
        teams = db.execute("SELECT team_id FROM teams WHERE created_at < ? ORDER BY team_id", (cutoff,)).fetchall()
        for (team,) in teams:
            db.execute("INSERT INTO snapshot_team_backlogs VALUES (?,?,?)", (sid, team, counts[team]))


def populate(db: sqlite3.Connection, seed: int):
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)
    used_ids: set[int] = set()

    def ident():
        while True:
            value = rng.randrange(100_000, 9_000_000)
            if value not in used_ids:
                used_ids.add(value)
                return value

    # All IDs are generated per seed, so equivalent cases cannot be memorized by ID.
    teams = sorted(rng.sample(range(11, 990), 9))
    top1, top2, top3, top4, source, target, empty, misc, april_only = teams
    team_names = ["Priority Desk", "Access Desk", "Billing Desk", "Product Desk",
                  "Escalations", "Routing Queue", "Quiet Queue", "General Support", "April Desk"]
    for tid, name in zip(teams, team_names):
        created = "2026-04-10 00:00:00" if tid == april_only else "2026-01-15 00:00:00"
        db.execute("INSERT INTO teams VALUES (?,?,?,NULL)", (tid, f"{name} {tid}", created))

    orgs = [ident() for _ in range(3)]
    for i, oid in enumerate(orgs):
        db.execute("INSERT INTO organizations VALUES (?,?,?)", (oid, f"{fake.company()} {i}", "2025-11-01 00:00:00"))
    customers = []
    for i in range(14):
        cid = ident(); customers.append(cid)
        db.execute("INSERT INTO customers VALUES (?,?,?,?,?)",
                   (cid, orgs[i % len(orgs)], fake.name(), f"customer{seed}_{i}@example.test", "2025-12-01 00:00:00"))
    agent_ids = []
    for i, tid in enumerate(teams[:8]):
        aid = ident(); agent_ids.append(aid)
        db.execute("INSERT INTO agents VALUES (?,?,?,?,?,?,?)",
                   (aid, tid, fake.name(), f"agent{seed}_{i}@example.test", 1, "senior_agent" if i % 3 == 0 else "agent", "2025-12-01 00:00:00"))
        db.execute("INSERT INTO agent_team_history VALUES (?,?,?,?,?)", (ident(), aid, tid, "2025-12-01 00:00:00", None))
    bot = ident()
    db.execute("INSERT INTO agents VALUES (?,?,?,?,?,?,?)",
               (bot, misc, "Automated Assistant", f"bot{seed}@example.test", 0, "agent", "2025-12-01 00:00:00"))
    db.execute("INSERT INTO agent_team_history VALUES (?,?,?,?,?)", (ident(), bot, misc, "2025-12-01 00:00:00", None))
    channels = [(1, "email"), (2, "portal"), (3, "phone")]
    priorities = [(1, "high", 1), (2, "normal", 2), (3, "low", 3)]
    db.executemany("INSERT INTO priorities VALUES (?,?,?)", priorities)
    db.executemany("INSERT INTO channels VALUES (?,?)", channels)
    for sid, name, priority, respond, resolve in ((1, "Urgent", 1, 30, 240), (2, "Standard", 2, 120, 1440), (3, "Low", 3, 480, 4320)):
        db.execute("INSERT INTO sla_policies VALUES (?,?,?,?,?)", (sid, name, priority, respond, resolve))
    db.executemany("INSERT INTO ticket_statuses VALUES (?,?,?)", [("open", "Open", 1), ("pending", "Pending", 1), ("closed", "Closed", 0)])
    db.executemany("INSERT INTO event_types VALUES (?,?)", [("created", "Ticket created"), ("status_changed", "Ticket status transition"), ("team_transferred", "Owning team changed"), ("message", "Message on ticket")])
    tag_ids = [ident() for _ in range(5)]
    for tid, tag in zip(tag_ids, ("billing", "access", "incident", "how_to", "follow_up")):
        db.execute("INSERT INTO tags VALUES (?,?)", (tid, tag))
    db.execute("INSERT INTO auto_response_rules VALUES (?,?,?,?,?,?)", (1, "Email acknowledgement", 1, "We received your request.", 1, "2025-12-01 00:00:00"))
    db.execute("INSERT INTO auto_response_rules VALUES (?,?,?,?,?,?)", (2, "Portal acknowledgement", 2, "Your request is in the queue.", 1, "2025-12-02 00:00:00"))

    state = {}
    ticket_customer = {}
    ticket_events = defaultdict(list)
    event_id_by_ticket = defaultdict(list)

    def event(tid, at, kind, status=None, team=None, from_status=None, from_team=None, reason=None,
              message=None, attachment=False):
        seq = len(ticket_events[tid]) + 1
        eid = ident()
        db.execute("INSERT INTO ticket_events VALUES (?,?,?,?,?)", (eid, tid, seq, at, kind))
        ticket_events[tid].append((eid, seq, at, kind))
        event_id_by_ticket[tid].append(eid)
        if kind in ("created", "status_changed"):
            db.execute("INSERT INTO ticket_status_events VALUES (?,?,?,?,?)", (eid, tid, from_status, status, reason))
            state[tid]["status"] = status
        if kind in ("created", "team_transferred"):
            db.execute("INSERT INTO ticket_assignment_events VALUES (?,?,?,?)", (eid, tid, from_team, team))
            state[tid]["team"] = team
        if message:
            author_kind, customer_id, agent_id, visibility, automated, rule_id, body = message
            db.execute("INSERT INTO ticket_messages VALUES (?,?,?,?,?,?,?,?,?)",
                       (eid, tid, author_kind, customer_id, agent_id, visibility, automated, rule_id, body))
        if attachment:
            db.execute("INSERT INTO ticket_attachments VALUES (?,?,?,?,?,?,?)",
                       (ident(), eid, tid, "customer", f"attachment-{eid}.txt", rng.randrange(128, 180000), at))
        return eid

    def ticket(at, team, customer=None, subject="Support request", status="open"):
        tid = ident(); cid = customer or rng.choice(customers)
        ticket_customer[tid] = cid
        pri = 1 + rng.randrange(3); channel = 1 + rng.randrange(3)
        db.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?)", (tid, cid, pri, channel, subject, at))
        state[tid] = {"status": None, "team": None}
        event(tid, at, "created", status="open", team=team, reason="created")
        if status != "open":
            event(tid, at, "status_changed", status=status, from_status="open", reason="initial_status")
        # Auxiliary records have valid references and realistic dates.
        db.execute("INSERT INTO ticket_sla VALUES (?,?,?,?,?,?,?)",
                   (ident(), tid, pri, at, "2026-05-20 00:00:00", None, 0))
        if rng.random() < 0.35:
            db.execute("INSERT INTO ticket_tag_map VALUES (?,?)", (tid, rng.choice(tag_ids)))
        if rng.random() < 0.18:
            score = 1 + rng.randrange(5)
            db.execute("INSERT INTO ticket_satisfaction VALUES (?,?,?,?,?,?)",
                       (ident(), tid, cid, score, rng.choice(["Helpful", "Resolved", "Still investigating", None]), "2026-04-25 12:00:00"))
        return tid

    def change(tid, at, to, reason=None):
        before = state[tid]["status"]
        assert before != to
        event(tid, at, "status_changed", status=to, from_status=before, reason=reason or "status_update")

    def transfer(tid, at, team):
        before = state[tid]["team"]
        assert before != team
        event(tid, at, "team_transferred", team=team, from_team=before)

    def message(tid, at, author, *, customer=None, agent=None, visibility="public", automated=0, rule=None, body=None):
        event(tid, at, "message", message=(author, customer, agent, visibility, automated, rule,
                                              body or f"Synthetic {author} update for case {tid}."),
              attachment=(author == "customer" and rng.random() < 0.3))

    # Backlog pools: each seed keeps the third/fourth place tie but varies counts and IDs.
    shift = (seed % 3)
    desired = [6 + shift, 5 + shift, 4 + shift, 4 + shift]
    pool_tickets = []
    for group, (team, count) in enumerate(zip((top1, top2, top3, top4), desired)):
        for i in range(count):
            created_day = 2 + ((i * 3 + group) % 25)
            tid = ticket(f"2026-03-{created_day:02d} {9 + (i % 8):02d}:{(i * 7) % 60:02d}:00", team,
                         subject=f"{fake.catch_phrase()} #{group}-{i}")
            pool_tickets.append(tid)
        # One pending ticket per team proves pending is included in backlog.
        change(pool_tickets[-1], f"2026-03-{25 + group:02d} 15:00:00", "pending", "awaiting_customer")

    # Dedicated Q1 cutoff cases and Q2 owner/team existence cases.
    boundary = ticket("2026-03-03 09:30:00", misc, subject="Pending through March cutoff")
    change(boundary, "2026-03-10 09:30:00", "pending", "awaiting_customer")
    change(boundary, MARCH, "closed", "cutoff_close")
    created_at_cutoff = ticket(MARCH, misc, subject="Created at March cutoff")
    transfer_case = ticket("2026-03-04 12:00:00", source, subject="Transfer exactly at cutoff")
    transfer(transfer_case, MARCH, target)
    closed_in_march = ticket("2026-03-01 00:00:00", misc, subject="March-start ticket closed before cutoff")
    change(closed_in_march, "2026-03-31 23:59:59", "closed", "resolved")

    # Q3: previously closed, reopened twice during March; an April-only reopen is the negative case.
    reopen_twice = ticket("2026-02-10 09:00:00", misc, subject="Multiple reopenings")
    change(reopen_twice, "2026-02-20 10:00:00", "closed")
    change(reopen_twice, "2026-03-05 10:00:00", "open", "reopened")
    change(reopen_twice, "2026-03-12 10:00:00", "closed")
    change(reopen_twice, "2026-03-25 10:00:00", "pending", "reopened")
    change(reopen_twice, "2026-03-28 10:00:00", "closed")
    april_reopen = ticket("2026-03-01 09:00:00", misc, subject="Reopens only in April")
    change(april_reopen, "2026-03-10 10:00:00", "closed")
    change(april_reopen, "2026-04-05 10:00:00", "open", "reopened")

    # Q4: public-human-after-first-customer rules, with private, bot, ordering, and cutoff counterexamples.
    q4_private = ticket("2026-03-01 10:00:00", source, subject="Private and automated reply only")
    message(q4_private, "2026-03-15 10:00:00", "customer", customer=ticket_customer[q4_private])
    message(q4_private, "2026-03-16 09:00:00", "agent", agent=agent_ids[0], visibility="private")
    message(q4_private, "2026-03-16 09:05:00", "system", automated=1, rule=1)
    message(q4_private, "2026-04-05 10:00:00", "agent", agent=agent_ids[1])
    q4_answered = ticket("2026-03-02 10:00:00", misc, subject="Answered publicly in March")
    message(q4_answered, "2026-03-15 11:00:00", "customer", customer=ticket_customer[q4_answered])
    message(q4_answered, "2026-03-20 10:00:00", "agent", agent=agent_ids[0])
    q4_april_customer = ticket("2026-03-10 10:00:00", empty, subject="First customer contact is April")
    message(q4_april_customer, "2026-04-02 10:00:00", "customer", customer=ticket_customer[q4_april_customer])
    q4_pre_reply = ticket("2026-03-08 10:00:00", source, subject="Agent message precedes customer")
    message(q4_pre_reply, "2026-03-10 10:00:00", "agent", agent=agent_ids[2])
    message(q4_pre_reply, "2026-03-12 10:00:00", "customer", customer=ticket_customer[q4_pre_reply])
    q4_bot = ticket("2026-03-09 10:00:00", misc, subject="Bot is not a human reply")
    message(q4_bot, "2026-03-14 10:00:00", "customer", customer=ticket_customer[q4_bot])
    message(q4_bot, "2026-03-15 10:00:00", "agent", agent=bot)

    # Q6: April closure, close/reopen at same timestamp with increasing sequence, and pre-March closure.
    q6_closed = ticket("2026-03-05 10:00:00", empty, subject="March open, April closed")
    change(q6_closed, "2026-04-10 14:00:00", "closed")
    q6_reopen = ticket("2026-03-06 11:00:00", empty, subject="Same-time close then reopen")
    change(q6_reopen, "2026-04-20 10:00:00", "closed")
    change(q6_reopen, "2026-04-20 10:00:00", "open", "reopened")
    preclosed = ticket("2026-02-01 08:00:00", misc, subject="Closed before March")
    change(preclosed, "2026-02-15 09:00:00", "closed")

    # A few ordinary open and April-only tickets keep the worlds less fixture-like.
    for i in range(3 + (seed % 3)):
        ticket(f"2026-03-{12 + i:02d} {10 + i:02d}:20:00", top1,
               subject=fake.sentence(nb_words=5))
    ticket("2026-04-12 10:00:00", april_only, subject="April intake")

    # Link a small number of cases without creating self-relations.
    tid_list = list(ticket_customer)
    if len(tid_list) >= 3:
        db.execute("INSERT INTO ticket_relations VALUES (?,?,?,?)", (ident(), tid_list[0], tid_list[1], "related_to"))
        db.execute("INSERT INTO ticket_relations VALUES (?,?,?,?)", (ident(), tid_list[1], tid_list[2], "caused_by"))

    # Materialize event-derived snapshots only after all April events have been written.
    rebuild_snapshots(db)
    db.commit()
    expected = derive_answers(db)
    march = _last_state(db, MARCH)
    march_counts = defaultdict(int)
    for snapshot_state in march.values():
        if snapshot_state["status"] in ("open", "pending"):
            march_counts[snapshot_state["team"]] += 1
    ranked = sorted(((team, count) for team, count in march_counts.items() if count),
                    key=lambda pair: (-pair[1], pair[0]))
    reopen_count = db.execute(
        "SELECT COUNT(*) FROM ticket_status_events s JOIN ticket_events e ON e.event_id=s.event_id "
        "WHERE s.ticket_id=? AND s.from_status='closed' AND s.to_status IN ('open','pending') "
        "AND e.occurred_at>=? AND e.occurred_at<?", (reopen_twice, MARCH_START, MARCH)
    ).fetchone()[0]
    same_time = ",".join(r[0] for r in db.execute(
        "SELECT s.to_status FROM ticket_status_events s JOIN ticket_events e ON e.event_id=s.event_id "
        "WHERE s.ticket_id=? AND e.occurred_at='2026-04-20 10:00:00' ORDER BY e.seq", (q6_reopen,)
    ))
    q4_rows = set(expected["Q4"])
    facts = {
        "march_boundary_pending_closes_april_1": march.get(boundary, {}).get("status") == "pending"
            and db.execute("SELECT 1 FROM ticket_status_events s JOIN ticket_events e ON e.event_id=s.event_id "
                           "WHERE s.ticket_id=? AND e.occurred_at=? AND s.to_status='closed'", (boundary, MARCH)).fetchone() is not None,
        "april_1_transfer_excluded_from_march": march.get(transfer_case, {}).get("team") == source
            and db.execute("SELECT 1 FROM ticket_assignment_events a JOIN ticket_events e ON e.event_id=a.event_id "
                           "WHERE a.ticket_id=? AND e.occurred_at=? AND a.to_team_id=?", (transfer_case, MARCH, target)).fetchone() is not None
            and march_counts.get(target, 0) == 0,
        "created_at_cutoff_absent_in_march": created_at_cutoff not in march,
        "team_tie_at_places_3_4": len(ranked) >= 4 and ranked[2][1] == ranked[3][1]
            and ranked[2][0] < ranked[3][0],
        "march_reopen_twice": reopen_count == 2 and (reopen_twice,) in expected["Q3"],
        "q4_edge_cases": (q4_private,) in q4_rows and (q4_pre_reply,) in q4_rows and (q4_bot,) in q4_rows
            and (q4_answered,) not in q4_rows and (q4_april_customer,) not in q4_rows,
        "same_timestamp_close_reopen": same_time == "closed,open"
            and march.get(q6_reopen, {}).get("status") in ("open", "pending"),
        "ticket_count": len(ticket_customer),
        "event_count": sum(map(len, ticket_events.values())),
    }
    failed_facts = [name for name, value in facts.items() if isinstance(value, bool) and not value]
    if failed_facts:
        raise ValueError(f"Seed {seed} scenario facts not covered: {failed_facts}")
    return expected, facts
