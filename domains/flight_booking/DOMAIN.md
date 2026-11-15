# Flight booking

Build an analytical snapshot of reservations on scheduled airline services. The data represents current passenger-level reservation status. A group booking can cover multiple travelers and several flight legs. A traveler can cancel just one leg while other travelers keep their reservations. The scope covers scheduled service and passenger reservations. Ticket prices, payments, check-in, actual movements and status history fall outside this snapshot.

## Schema and foreign keys

Every listed column is required. Surrogate IDs are unique integers. Each foreign key below references a primary key and permits many child rows per parent. A parent may have zero child rows. The SQLite DDL defines the exact types, checks and keys.

| Table | One row represents | Columns and relationships |
| --- | --- | --- |
| airports | One airport | id (PK), code (unique three-letter uppercase identifier), name |
| airlines | One marketing carrier | id (PK), code (unique two-character identifier), name |
| aircraft_types | One aircraft model | id (PK), model (unique) |
| aircraft | One registered aircraft | id (PK), registration (unique), aircraft_type_id → aircraft_types.id, airline_id → airlines.id (fleet owner) |
| routes | One directional airport pair | id (PK), origin_airport_id and destination_airport_id → airports.id. The pair is unique and the endpoints must differ. |
| flights | One recurring marketed flight number on a fixed route | id (PK), airline_id → airlines.id, number (text), route_id → routes.id. The carrier and number together are unique. |
| departures | One dated instance of a recurring flight | id (PK), flight_id → flights.id, departs_at, arrives_at, aircraft_id → aircraft.id. Flight and departure timestamp together are unique. |
| bookings | One reservation record | id (PK), reference (unique) |
| passengers | One synthetic traveler | id (PK), full_name. Travelers may share a name. |
| booking_passengers | One traveler's membership in a booking | booking_id → bookings.id, passenger_id → passengers.id. Together they form the PK. |
| booking_legs | One numbered itinerary leg on a booking | booking_id → bookings.id, leg_no (positive), departure_id → departures.id. The PK is (booking_id, leg_no). A departure appears at most once per booking. |
| passenger_legs | One traveler's reservation status on a booked leg | (booking_id, passenger_id) → booking_passengers, (booking_id, leg_no) → booking_legs. The three IDs together form the PK. status is either confirmed or cancelled. |

All timestamps are UTC in YYYY-MM-DD HH:MM:SS format. Arrival follows departure. The aircraft fleet owner may differ from the marketing carrier. The two booking-scoped references on passenger_legs require the traveler and the itinerary leg to belong to the same booking. Travelers may participate in different subsets of an itinerary. A missing passenger-leg row indicates the traveler never reserved that leg. Cancellation preserves the passenger-leg row with its updated status.

## Questions the snapshot must support

1. For each scheduled departure, how many passenger-leg reservations are confirmed? Include departures with zero confirmations.
2. Which bookings contain more than one traveler? Count booking membership, including travelers who cancelled their legs.
3. Which departure IDs have no confirmed passengers? Include departures with only cancellations and departures with no reservations.
4. Which bookings contain a traveler who has both a confirmed leg and a cancelled leg on that same booking?
5. How many departures are scheduled for each recurring flight? Include flights with no scheduled departures.
6. For each destination airport, how many confirmed passenger-leg reservations arrive there? Include airports with a count of zero.

Counts of confirmed passengers on a departure refer to confirmed passenger-leg reservations. A traveler who reserves the same departure under two separate bookings contributes two reservations. Airport-level counts sum confirmed reservations across departures. Booking membership, distinct traveler counts, reservation counts and scheduled departure counts therefore answer different questions.

## Review scenarios

- Two travelers share an outbound and return itinerary. One cancels just the return, leaving two confirmations outbound and one inbound.
- The same marketed flight number operates on two dates. Counts attach to each dated departure separately.
- An additional departure has only cancelled reservations, another has no reservations, and a recurring flight has no scheduled departure.
- Two different travelers in the same booking each have a single status. Their rows must not imply that either traveler individually holds both statuses.
- An attempted assignment of a traveler to a leg from an unrelated booking must fail. A second assignment to the same traveler and booked leg must also fail.
