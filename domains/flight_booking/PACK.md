# Rebuild the flight-booking dataset

Extract the ZIP and run these commands inside its synthdb/domains/flight_booking directory. The archive includes the reviewed schema and relationship map, generator, independent review fixture, original pilot data, Pi design harness and the OpenRouter build command.

```bash
runner=/home/sagar/miniconda3/bin/conda
"$runner" run -n base python -m pip install -r ../../requirements.txt
read -rsp 'OpenRouter API key: ' OPENROUTER_API_KEY && echo
export OPENROUTER_API_KEY
"$runner" run -n base python free_build.py flight-openrouter --seed 41 --worlds 3
```

The default model is liquid/lfm-3-1.7b:free. Use --model to select another explicit :free OpenRouter model. The script sends only the SQLite DDL, one reviewed question and, on a correction attempt, the previous candidate SQL. The independent grader stays local. A new output name starts a fresh run. Reusing an unfinished output name resumes from its sibling .run.json journal. Use one process per output name.

The same seed and pinned Faker version reproduce the same worlds in the original runtime. The model authors a candidate SELECT for each of six question families in separate requests. Only answers that pass all three split worlds (by default) and the independent hand-built fixture enter the export. A failed family blocks publication and remains in the journal for retry. The prompts and expected answers stay fixed for comparability. Model responses can vary. See generation.json for all attempts and manifest.json for provenance.

For an offline rebuild with the bundled reference SQL:

```bash
"$runner" run -n base python free_build.py flight-replay --replay
```

For a new schema, see the sequential author and reviewer workflow in [the project README](../../README.md). This archive's generator targets the included flight-booking schema.
