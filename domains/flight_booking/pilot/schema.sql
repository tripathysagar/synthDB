PRAGMA foreign_keys = ON;

CREATE TABLE airports (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE CHECK (code GLOB '[A-Z][A-Z][A-Z]'),
    name TEXT NOT NULL
) STRICT;

CREATE TABLE airlines (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE CHECK (length(code) = 2 AND code NOT GLOB '*[^A-Z0-9]*'),
    name TEXT NOT NULL
) STRICT;

CREATE TABLE aircraft_types (
    id INTEGER PRIMARY KEY,
    model TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE aircraft (
    id INTEGER PRIMARY KEY,
    registration TEXT NOT NULL UNIQUE,
    aircraft_type_id INTEGER NOT NULL REFERENCES aircraft_types(id),
    airline_id INTEGER NOT NULL REFERENCES airlines(id)
) STRICT;

CREATE TABLE routes (
    id INTEGER PRIMARY KEY,
    origin_airport_id INTEGER NOT NULL REFERENCES airports(id),
    destination_airport_id INTEGER NOT NULL REFERENCES airports(id),
    CHECK (origin_airport_id <> destination_airport_id),
    UNIQUE (origin_airport_id, destination_airport_id)
) STRICT;

CREATE TABLE flights (
    id INTEGER PRIMARY KEY,
    airline_id INTEGER NOT NULL REFERENCES airlines(id),
    number TEXT NOT NULL,
    route_id INTEGER NOT NULL REFERENCES routes(id),
    UNIQUE (airline_id, number)
) STRICT;

CREATE TABLE departures (
    id INTEGER PRIMARY KEY,
    flight_id INTEGER NOT NULL REFERENCES flights(id),
    departs_at TEXT NOT NULL CHECK (strftime('%Y-%m-%d %H:%M:%S', departs_at, '+0 seconds') IS departs_at),
    arrives_at TEXT NOT NULL CHECK (strftime('%Y-%m-%d %H:%M:%S', arrives_at, '+0 seconds') IS arrives_at),
    aircraft_id INTEGER NOT NULL REFERENCES aircraft(id),
    CHECK (arrives_at > departs_at),
    UNIQUE (flight_id, departs_at)
) STRICT;

CREATE TABLE bookings (
    id INTEGER PRIMARY KEY,
    reference TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE passengers (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL
) STRICT;

CREATE TABLE booking_passengers (
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    passenger_id INTEGER NOT NULL REFERENCES passengers(id),
    PRIMARY KEY (booking_id, passenger_id)
) STRICT;

CREATE TABLE booking_legs (
    booking_id INTEGER NOT NULL REFERENCES bookings(id),
    leg_no INTEGER NOT NULL CHECK (leg_no > 0),
    departure_id INTEGER NOT NULL REFERENCES departures(id),
    PRIMARY KEY (booking_id, leg_no),
    UNIQUE (booking_id, departure_id)
) STRICT;

CREATE TABLE passenger_legs (
    booking_id INTEGER NOT NULL,
    passenger_id INTEGER NOT NULL,
    leg_no INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'cancelled')),
    PRIMARY KEY (booking_id, passenger_id, leg_no),
    FOREIGN KEY (booking_id, passenger_id) REFERENCES booking_passengers(booking_id, passenger_id),
    FOREIGN KEY (booking_id, leg_no) REFERENCES booking_legs(booking_id, leg_no)
) STRICT;

CREATE INDEX booking_legs_by_departure ON booking_legs(departure_id);
