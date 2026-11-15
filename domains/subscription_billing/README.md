# Subscription billing pilot

Eleven SQLite tables model customers, subscriptions, invoices, payments and credits. See DOMAIN.md for grain and rules and brief.md for the six target questions. The pilot contains nine worlds with seeds 101–109. There are nine train examples, three validation examples, and six test examples. The nine worlds repeat six question texts.

Run from this domain directory in WSL:

```bash
/home/sagar/miniconda3/bin/conda run -n base python build.py review
```

To regenerate, copy the source tree to a fresh directory with the same project layout and omit pilot/. Run build.py there. It refuses to overwrite an existing pilot. The builder verifies every family in every world against the event-based Python oracle before publishing split-specific prompts and answers. Only prompts.jsonl, schema.sql and the corresponding world database belong on the solver side.

Inkling 2 Small (free) via OpenRouter and Pi authored the design, hand-built fixture, question checks and Faker generator. Local verification led to repairs to date validation, allocation ownership and chronology, spending limits, the March invoice cutoff for Q5/Q6, and the tie-break counterexample. pilot/manifest.json records the final checks and repair history. An initial combined reviewer session produced no file. The successful review used fixture.sql followed by three independent two-question batches. run_inkling.py supports rerunning individual model stages with OPENROUTER_API_KEY in the environment. build.py assemble combines the batches and executes the fixture checks before publishing review.json.
