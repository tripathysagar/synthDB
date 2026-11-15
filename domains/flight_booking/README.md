# Flight booking

Build a Text2SQL dataset whose reference answers survive a separate schema review. The flight-booking pilot ships with a 12-table SQLite schema, a reviewer-owned fixture, and six question families. DOMAIN.md describes the grain of each table and the foreign-key map.

## Run in WSL

Run these commands from the domains/flight_booking directory. The build requires Python 3.10+ and SQLite 3.37+.

```bash
py=/home/sagar/miniconda3/bin/conda
"$py" run -n base python -m pip install -r ../../requirements.txt
"$py" run -n base python synthdb.py review
"$py" run -n base python synthdb.py build another-dataset --seed 41 --worlds 3
"$py" run -n base python synthdb.py grade pilot group_bookings candidate.sql
```

The checked build is in `pilot/`. Each split has SQLite worlds and two JSONL files keyed by example ID. Give the solver the question, database and schema. Retain `answers.jsonl`, `manifest.json` and `review.sqlite` on the evaluator side. Each family belongs to one split and each seed belongs to one split. The pilot repeats a fixed question on different worlds. Its 18 examples represent six distinct questions.

Review loads the schema into SQLite and tests hand-calculated answers, invalid relationships and plausible wrong queries. Build runs review before generation. Seeded Faker supplies names while flight_world.py creates connected bookings and counts expected results directly from reservation events. Build checks all six reference queries in every generated world before exporting a split. Grade compares unordered rows including multiplicity and result width. Reward is one only if the candidate passes every world in the family’s split and the independent review fixture.

See [PACK.md](PACK.md) for OpenRouter generation and offline replay.
