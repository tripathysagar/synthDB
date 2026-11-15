"""Rebuild flight booking and export SQL verified on seeded worlds and reviewer data."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from questions import FAMILIES
from synthdb import build, grade

DEFAULT_MODEL = "liquid/lfm-3-1.7b:free"
API = "https://openrouter.ai/api/v1/chat/completions"


def request_sql(key, model, schema, question, feedback):
    prompt = f"SQLite schema:\n{schema}\nQuestion: {question}\n{feedback}"
    body = {"model": model, "temperature": 0, "max_tokens": 4096, "messages": [
        {"role": "system", "content": "Return only one SQLite SELECT query. Preserve result columns in the requested order."},
        {"role": "user", "content": prompt}]}
    req = Request(API, json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=120) as response:
                result = json.load(response)
            break
        except HTTPError as error:
            if error.code not in (429, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"OpenRouter HTTP {error.code}. Check the key, free quota and model availability.") from error
            delay = error.headers.get("Retry-After", "")
            if delay.isdecimal() and int(delay) > 60:
                raise RuntimeError(f"OpenRouter requests a retry after {delay}s. Re-run later.") from error
            time.sleep(int(delay) if delay.isdecimal() else 3 * (attempt + 1))
    if "error" in result or not result.get("choices"):
        raise RuntimeError("OpenRouter returned no completion. Re-run to resume.")
    choice = result["choices"][0]
    raw = (choice["message"].get("content") or "").strip()
    fenced = re.fullmatch(r"```(?:sql|sqlite)?\s*(.*?)\s*```", raw, re.S | re.I)
    return (fenced.group(1) if fenced else raw), result.get("model",model)


def save(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def run(output, seed, worlds, model, replay):
    if output.exists():
        raise ValueError("Output already exists. Choose a new dataset directory.")
    if not replay and not model.endswith(":free"):
        raise ValueError("Choose an explicit OpenRouter :free model ID.")
    key = os.getenv("OPENROUTER_API_KEY")
    if not replay and not key:
        raise ValueError("Set OPENROUTER_API_KEY in the WSL environment, or use --replay for the offline baseline.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        dataset = Path(temp)/"dataset"
        build(dataset, seed, worlds)
        schema = (dataset/"schema.sql").read_text()
        config = {"source": "reviewed-reference" if replay else "openrouter",
                  "model": None if replay else model, "seed": seed, "worlds": worlds,
                  "schema_sha256": hashlib.sha256(schema.encode()).hexdigest()}
        journal = output.with_name(output.name + ".run.json")
        state = json.loads(journal.read_text()) if journal.exists() else {"config":config,"accepted":{},"attempts":[]}
        if state["config"] != config:
            raise ValueError(f"Run configuration differs from {journal}. Choose a new output name.")
        save(journal, state)
        for family, (question, reference) in FAMILIES.items():
            accepted = state["accepted"].get(family)
            if accepted and grade(dataset, family, accepted["sql"])["reward"]:
                continue
            feedback = ""
            for _ in range(1 if replay else 3):
                sql, actual = (reference, None) if replay else request_sql(key, model, schema, question, feedback)
                result = grade(dataset, family, sql)
                state["attempts"].append({"family":family, "sql":sql, "model":actual, **result})
                if result["reward"]:
                    state["accepted"][family] = {"sql":sql,"model":actual}
                save(journal, state)
                if result["reward"]:
                    break
                feedback = f"Previous SQL failed a result check. Reconsider joins, status filters, and zero counts.\nPrevious SQL: {sql}"
            else:
                raise ValueError(f"No accepted SQL for {family}. Inspect {journal} and re-run to retry.")
        for path in dataset.glob("*/answers.jsonl"):
            records = [json.loads(line) for line in path.read_text().splitlines()]
            for record in records:
                record["sql"] = state["accepted"][record["family"]]["sql"]
            path.write_text("".join(json.dumps(row)+"\n" for row in records))
        manifest = json.loads((dataset/"manifest.json").read_text())
        manifest["sql_generation"] = config
        save(dataset/"manifest.json", manifest)
        save(dataset/"generation.json", state)
        dataset.rename(output)
    print(output.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--worlds", type=int, default=3)
    parser.add_argument("--replay", action="store_true", help="use bundled reviewed SQL; no API request")
    args = parser.parse_args()
    try:
        run(args.output, args.seed, args.worlds, args.model, args.replay)
    except (ValueError, RuntimeError, URLError) as error:
        sys.exit(str(error))
