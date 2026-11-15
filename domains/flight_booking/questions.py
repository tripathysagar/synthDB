"""Flight-booking questions. Every result is an unordered multiset of rows."""

FAMILIES = {
    "confirmed_per_departure": (
        "For every departure, give its ID and the number of confirmed passenger-leg reservations, including zero.",
        """SELECT d.id, count(p.passenger_id)
           FROM departures d LEFT JOIN booking_legs l ON l.departure_id=d.id
           LEFT JOIN passenger_legs p ON (p.booking_id,p.leg_no)=(l.booking_id,l.leg_no)
             AND p.status='confirmed' GROUP BY d.id""",
    ),
    "group_bookings": (
        "Which booking IDs have more than one passenger?",
        "SELECT booking_id FROM booking_passengers GROUP BY booking_id HAVING count(*)>1",
    ),
    "empty_departures": (
        "Which departure IDs have zero confirmed passengers?",
        """SELECT d.id FROM departures d WHERE NOT EXISTS (
           SELECT 1 FROM booking_legs l JOIN passenger_legs p USING (booking_id,leg_no)
           WHERE l.departure_id=d.id AND p.status='confirmed')""",
    ),
    "partial_cancellations": (
        "Which distinct booking IDs contain a passenger with both a confirmed leg and a cancelled leg?",
        """SELECT DISTINCT booking_id FROM passenger_legs GROUP BY booking_id,passenger_id
           HAVING count(DISTINCT status)=2""",
    ),
    "departures_per_flight": (
        "For each flight ID, how many departures are scheduled? Include flights with none.",
        "SELECT f.id,count(d.id) FROM flights f LEFT JOIN departures d ON d.flight_id=f.id GROUP BY f.id",
    ),
    "confirmed_by_destination": (
        "For every airport ID, count confirmed passenger legs arriving there, including zero.",
        """SELECT a.id,count(p.passenger_id) FROM airports a
           LEFT JOIN routes r ON r.destination_airport_id=a.id
           LEFT JOIN flights f ON f.route_id=r.id LEFT JOIN departures d ON d.flight_id=f.id
           LEFT JOIN booking_legs l ON l.departure_id=d.id
           LEFT JOIN passenger_legs p ON (p.booking_id,p.leg_no)=(l.booking_id,l.leg_no)
             AND p.status='confirmed' GROUP BY a.id""",
    ),
}

SPLIT = {"confirmed_per_departure": "train", "group_bookings": "train",
         "empty_departures": "validation", "partial_cancellations": "test",
         "departures_per_flight": "train", "confirmed_by_destination": "test"}
