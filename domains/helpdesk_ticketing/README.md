# Helpdesk ticketing pilot

The helpdesk domain contains six historical Text2SQL questions over an
event-sourced SQLite schema. See [DOMAIN.md](DOMAIN.md) for the table grain,
cutoff semantics, and fixture evidence.

## Release contents

- `pilot/train`, `pilot/validation`, and `pilot/test` contain solver prompts
  and nine world databases. Each split holds three seeded worlds.
- `pilot/evaluator/answers/` holds answer SQL and expected rows separately from
  the solver directories.
- `pilot/manifest.json` records seeds, coverage, model provenance, and audit
  results. `pilot/review.sqlite` is the frozen fixture.
- `schema.sql`, `fixture.sql`, and `review.json` are the frozen design inputs.

Question families are assigned as Q1–Q3 to train, Q4 to validation, and Q5–Q6
to test. The generator uses seeds 101/104/107, 102/105/108, and 103/106/109
respectively. Each world is checked against all six SQL questions and an
independent Python event replay. Paired wrong queries, FK enforcement,
SQLite integrity, and March snapshot reproducibility are checked too.

## Commands (WSL)

Run from this directory using the repository Conda base environment:

```bash
/home/sagar/miniconda3/bin/conda run -n base python build.py review
/home/sagar/miniconda3/bin/conda run -n base python build.py audit
```

To generate a fresh `pilot/`, run `python build.py build`. The build refuses to
overwrite an existing pilot; preserve or move it aside explicitly before
regenerating.

The saved Pi design run names `thinkingmachines/inkling-2-small:free`. Pi and
its OpenRouter API key were unavailable during the release build, so the seeded
world generator and builder were authored locally. The requested 5.6 Luna
light review model was unavailable; an independent collaborator used the
closest available `gpt-6-luna` model and reported no release blockers.
