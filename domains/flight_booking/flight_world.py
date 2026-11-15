"""Build relational events and their expected answers before writing SQLite rows."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from random import Random

from faker import Faker


def populate(db, seed):
    rng = Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)

    def insert(table, *values):
        marks = ",".join("?" for _ in values)
        db.execute(f"INSERT INTO {table} VALUES ({marks})", values)

    for idx, code in enumerate(("DEL", "BOM", "BLR"), 1):
        insert("airports", idx, code, fake.city() + " Airport")
    insert("airlines", 1, "ZX", "Synthetic Air")
    insert("aircraft_types", 1, "A320")
    insert("aircraft", 1, "VT-ZXA", 1, 1)
    insert("aircraft", 2, "VT-ZXB", 1, 1)
    destinations = {1: 2, 2: 1, 3: 3}
    for route, origin in ((1, 1), (2, 2), (3, 1)):
        insert("routes", route, origin, destinations[route])
        insert("flights", route, 1, str(100 + route), route)

    departure_counts = Counter()
    legs_per_airport = Counter()
    per_flight = Counter()
    dep_flight = {}
    days = rng.randint(4, 8)
    for day in range(days):
        for flight in (1, 2):
            dep = day * 2 + flight
            start = datetime(2026, 1, 1, 6) + timedelta(days=day, hours=6*(flight-1))
            insert("departures", dep, flight, str(start), str(start + timedelta(hours=2)), 1+day%2)
            dep_flight[dep] = flight
            per_flight[flight] += 1

    partial = []
    groups = []
    passenger = 0
    def book(booking, departures, statuses):
        nonlocal passenger
        insert("bookings", booking, f"B{booking:05d}")
        for leg, dep in enumerate(departures, 1):
            insert("booking_legs", booking, leg, dep)
        if len(statuses) > 1:
            groups.append((booking,))
        if any(len(set(person)) > 1 for person in statuses):
            partial.append((booking,))
        for person in statuses:
            passenger += 1
            insert("passengers", passenger, fake.name())
            insert("booking_passengers", booking, passenger)
            for leg, (dep, status) in enumerate(zip(departures, person, strict=True), 1):
                insert("passenger_legs", booking, passenger, leg, status)
                if status == "confirmed":
                    departure_counts[dep] += 1
                    legs_per_airport[destinations[dep_flight[dep]]] += 1

    book(1, [1, 2], [["confirmed", "confirmed"], ["confirmed", "cancelled"]])
    book(2, [3], [["cancelled"]])
    # Departure 4 is deliberately unbooked. Random traffic starts on day three.
    for booking in range(3, rng.randint(15, 35)):
        outbound = 2*rng.randrange(2, days) + 1
        deps = [outbound, outbound+1] if rng.random()<0.6 else [outbound]
        statuses = [rng.choices(["confirmed", "cancelled"], weights=[4, 1], k=len(deps))
                    for _ in range(rng.randint(1, 4))]
        book(booking, deps, statuses)
    return {
        "confirmed_per_departure": [(dep, departure_counts[dep]) for dep in dep_flight],
        "group_bookings": groups,
        "empty_departures": [(dep,) for dep in dep_flight if departure_counts[dep]==0],
        "partial_cancellations": partial,
        "departures_per_flight": [(f, per_flight[f]) for f in destinations],
        "confirmed_by_destination": [(a, legs_per_airport[a]) for a in (1,2,3)],
    }
