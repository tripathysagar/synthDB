"""Independent, deterministic schema review. No generator or model is required."""
from collections import Counter, defaultdict
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3

from questions import FAMILIES


FIXTURE = """
INSERT INTO airports VALUES (1,'AAA','Origin'),(2,'BBB','Destination'),(3,'CCC','Unused');
INSERT INTO airlines VALUES (1,'AB','Reviewer Air');
INSERT INTO aircraft_types VALUES (1,'Example');
INSERT INTO aircraft VALUES (1,'AB-1',1,1);
INSERT INTO routes VALUES (1,1,2),(2,2,1),(3,1,3);
INSERT INTO flights VALUES (11,1,'101',1),(12,1,'102',2),(13,1,'103',3);
INSERT INTO departures VALUES
 (10,11,'2026-10-01 09:00:00','2026-10-01 10:00:00',1),
 (20,12,'2026-10-01 12:00:00','2026-10-01 13:00:00',1),
 (30,11,'2026-10-02 09:00:00','2026-10-02 10:00:00',1),
 (40,12,'2026-10-02 12:00:00','2026-10-02 13:00:00',1);
INSERT INTO bookings VALUES (1,'ROUND'),(2,'MIX'),(3,'SINGLE');
INSERT INTO passengers VALUES (1,'A'),(2,'B'),(3,'C'),(4,'D');
INSERT INTO booking_passengers VALUES (1,1),(1,2),(2,3),(2,4),(3,1);
INSERT INTO booking_legs VALUES (1,1,10),(1,2,20),(2,1,20),(2,2,30),(3,1,20);
INSERT INTO passenger_legs VALUES
 (1,1,1,'confirmed'),(1,2,1,'confirmed'),(1,1,2,'confirmed'),(1,2,2,'cancelled'),
 (2,3,2,'cancelled'),(2,4,1,'confirmed'),(3,1,1,'confirmed');
"""

# Different oracle and different data from the synthetic world generator.
EXPECTED = {
    "confirmed_per_departure": [(10,2),(20,3),(30,0),(40,0)],
    "group_bookings": [(1,), (2,)],
    "empty_departures": [(30,), (40,)],
    "partial_cancellations": [(1,)],
    "departures_per_flight": [(11,2),(12,2),(13,0)],
    "confirmed_by_destination": [(1,3),(2,2),(3,0)],
}

# Every wrong query executes successfully. The fixture must distinguish its result.
WRONG = {
    "confirmed_per_departure": """SELECT d.id,count(DISTINCT p.passenger_id)
        FROM departures d LEFT JOIN booking_legs l ON d.id=l.departure_id
        LEFT JOIN passenger_legs p ON p.booking_id=l.booking_id AND p.leg_no=l.leg_no
        AND p.status='confirmed' GROUP BY d.id""",
    "group_bookings": """SELECT booking_id FROM passenger_legs WHERE status='confirmed'
        GROUP BY booking_id HAVING count(DISTINCT passenger_id)>1""",
    "empty_departures": "SELECT id FROM departures WHERE id NOT IN (SELECT departure_id FROM booking_legs)",
    "partial_cancellations": """SELECT booking_id FROM passenger_legs
        GROUP BY booking_id HAVING count(DISTINCT status)>1""",
    "departures_per_flight": "SELECT flight_id,count(*) FROM departures GROUP BY flight_id",
    "confirmed_by_destination": """SELECT a.id,count(p.passenger_id) FROM airports a
        LEFT JOIN routes r ON a.id=r.origin_airport_id LEFT JOIN flights f ON f.route_id=r.id
        LEFT JOIN departures d ON d.flight_id=f.id LEFT JOIN booking_legs l ON l.departure_id=d.id
        LEFT JOIN passenger_legs p ON p.booking_id=l.booking_id AND p.leg_no=l.leg_no
        AND p.status='confirmed' GROUP BY a.id""",
}

# Third field is the ordered list of child/parent column pairs for one FK.
FK_MAP = {
    ("aircraft","aircraft_types",(("aircraft_type_id","id"),)),
    ("aircraft","airlines",(("airline_id","id"),)),
    ("routes","airports",(("origin_airport_id","id"),)),
    ("routes","airports",(("destination_airport_id","id"),)),
    ("flights","airlines",(("airline_id","id"),)),
    ("flights","routes",(("route_id","id"),)),
    ("departures","flights",(("flight_id","id"),)),
    ("departures","aircraft",(("aircraft_id","id"),)),
    ("booking_passengers","bookings",(("booking_id","id"),)),
    ("booking_passengers","passengers",(("passenger_id","id"),)),
    ("booking_legs","bookings",(("booking_id","id"),)),
    ("booking_legs","departures",(("departure_id","id"),)),
    ("passenger_legs","booking_passengers",(("booking_id","booking_id"),("passenger_id","passenger_id"))),
    ("passenger_legs","booking_legs",(("booking_id","booking_id"),("leg_no","leg_no"))),
}

INVALID = {
    "traveler from another booking": "(2,1,1,'confirmed')",
    "leg from another booking": "(3,1,2,'confirmed')",
    "duplicate assignment": "(1,1,1,'confirmed')",
    "unknown status": "(2,3,1,'pending')",
}


def run_review():
    ddl = Path(__file__).with_name("schema.sql").read_bytes()
    with closing(sqlite3.connect(":memory:")) as db:
        db.executescript(ddl.decode("utf-8"))
        if db.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise ValueError("DDL did not enable foreign key enforcement")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        found = set()
        for table in tables:
            groups = defaultdict(list)
            for key, seq, parent, child_col, parent_col, *_ in db.execute(
                "SELECT * FROM pragma_foreign_key_list(?) ORDER BY id, seq", (table,)
            ):
                groups[(key, parent)].append((child_col, parent_col))
            found.update((table, parent, tuple(cols)) for (_, parent), cols in groups.items())
        if found != FK_MAP or tables != {name for child,parent,_ in FK_MAP for name in (child,parent)}:
            raise ValueError("Schema table or foreign-key map differs from the reviewed domain")
        db.executescript(FIXTURE)
        for name, values in INVALID.items():
            try:
                db.execute("INSERT INTO passenger_legs VALUES " + values)
            except sqlite3.IntegrityError as error:
                expected_error = {"duplicate assignment": "SQLITE_CONSTRAINT_PRIMARYKEY",
                                  "unknown status": "SQLITE_CONSTRAINT_CHECK"}.get(name, "SQLITE_CONSTRAINT_FOREIGNKEY")
                if error.sqlite_errorname != expected_error:
                    raise ValueError(f"{name}: unexpected constraint {error.sqlite_errorname}") from error
            else:
                raise ValueError(f"Invalid row accepted: {name}")
        if db.execute("PRAGMA foreign_key_check").fetchall() or db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Fixture integrity check failed")
        if set(FAMILIES) != set(EXPECTED) or set(EXPECTED) != set(WRONG):
            raise ValueError("Every question family requires an independent fixture and counterexample")
        for family, rows in EXPECTED.items():
            if Counter(db.execute(FAMILIES[family][1])) != Counter(rows):
                raise ValueError(f"Gold query disagrees with fixture: {family}")
            if Counter(db.execute(WRONG[family])) == Counter(rows):
                raise ValueError(f"Fixture failed to distinguish wrong query: {family}")
    return {"schema_sha256": sha256(ddl).hexdigest(), "tables": len(tables),
            "foreign_keys": len(found), "rejected_invalid_rows": list(INVALID),
            "fixture_expected_rows": EXPECTED, "rejected_wrong_queries": list(WRONG)}
