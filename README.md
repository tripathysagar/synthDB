# SynthDB

Each domain lives under `domains/<name>/`. The [flight-booking domain](domains/flight_booking/README.md) contains its schema, generator, grader, pilot dataset, and package instructions. Run domain builds from that directory so output datasets and journals stay together.

## Design another domain with Pi

With an authenticated Pi CLI available on PATH, write a domain brief containing the business rules and questions. Give each target question its own line, such as `[Q1] Which invoices were unpaid on March 31?`. For ranked or sequence-sensitive answers, use `[Q2] [ordered] List invoices by amount descending, breaking ties by invoice ID.` Pi loads the [project review skill](.agents/skills/text2sql-domain-review/SKILL.md) in both sessions.

```bash
/home/sagar/miniconda3/bin/conda run -n base python pi_design.py brief.md domains/billing/design --rounds 3
```

The harness starts separate tool-free Pi author and reviewer sessions. It saves the design and findings per round, executes the reviewer's fixtures and checks, and writes accepted.json after a passing round. An exhausted round limit leaves the design unresolved. After acceptance, implement the new domain’s generator, question families and independent expected answers. The included generator and grading CLI target flight booking.
