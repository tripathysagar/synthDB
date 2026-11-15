"""Build reviewed SQLite worlds and score one candidate on every world in its split."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from importlib.metadata import version

from flight_world import populate
from questions import FAMILIES, SPLIT
from review import FIXTURE, run_review

ROOT = Path(__file__).resolve().parent


def build(output, seed, worlds):
    if output.exists() or worlds < 1:
        raise ValueError("Choose a new output directory and at least one world per split.")
    proof = run_review()
    schema = (ROOT / "schema.sql").read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        stage = Path(temp) / "dataset"
        stage.mkdir()
        (stage / "schema.sql").write_bytes(schema)
        manifest = {"seed": seed, "worlds_per_split": worlds, "faker": version("Faker"),
                    "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
                    "schema_sha256": hashlib.sha256(schema).hexdigest(), "review": proof}
        with closing(sqlite3.connect(stage/"review.sqlite")) as db:
            db.executescript(schema.decode())
            db.executescript(FIXTURE)
        for split_index, split in enumerate(("train", "validation", "test")):
            directory = stage / split
            directory.mkdir()
            with (directory/"prompts.jsonl").open("w") as prompts, (directory/"answers.jsonl").open("w") as answers:
                for index in range(worlds):
                    world_seed = seed + index*3 + split_index
                    filename = f"world-{world_seed}.sqlite"
                    with closing(sqlite3.connect(directory / filename)) as db:
                        db.executescript(schema.decode())
                        with db:
                            expected = populate(db, world_seed)
                        if db.execute("PRAGMA foreign_key_check").fetchall():
                            raise ValueError(f"Broken relationships in {filename}")
                        for family, (question, sql) in FAMILIES.items():
                            rows = expected[family]
                            if Counter(db.execute(sql)) != Counter(rows):
                                raise ValueError(f"Wrong reference answer in {filename}: {family}")
                            if SPLIT[family] != split:
                                continue
                            entry = {"id": f"{world_seed}-{family}", "database": filename, "family": family}
                            print(json.dumps(dict(entry, question=question)), file=prompts)
                            print(json.dumps(dict(entry, sql=sql, rows=rows)), file=answers)
        (stage/"manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        stage.rename(output)


def grade(dataset, family, sql):
    directory = dataset / SPLIT[family]
    results = []
    records = [r for r in map(json.loads, (directory/"answers.jsonl").read_text().splitlines())
               if r["family"] == family]
    if not records:
        raise ValueError("Dataset has no worlds for this family.")
    manifest = json.loads((dataset/"manifest.json").read_text())
    records.append({"database": "../review.sqlite", "sql": records[0]["sql"],
                    "rows": manifest["review"]["fixture_expected_rows"][family]})
    for record in records:
        uri = (directory / record["database"]).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
            db.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
            ticks = iter(range(5000))
            db.set_progress_handler(lambda: next(ticks, None) is None, 1000)
            expected = Counter(tuple(row) for row in record["rows"])
            try:
                cursor = db.execute(sql)
                reference_width = len(db.execute(record["sql"]).description)
                rows = cursor.fetchmany(len(record["rows"])+1)
                passed = bool(cursor.description) and len(cursor.description)==reference_width and Counter(rows)==expected
            except sqlite3.Error:
                passed = False
            results.append({"database": record["database"], "passed": passed})
    return {"reward": int(all(r["passed"] for r in results)), "worlds": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("review")
    create = commands.add_parser("build")
    create.add_argument("output", type=Path)
    create.add_argument("--seed", type=int, default=41)
    create.add_argument("--worlds", type=int, default=3, help="worlds per split")
    score = commands.add_parser("grade")
    score.add_argument("dataset", type=Path)
    score.add_argument("family", choices=FAMILIES)
    score.add_argument("sql", type=Path)
    args = parser.parse_args()
    if args.command == "review":
        print(json.dumps(run_review(), indent=2))
    elif args.command == "build":
        build(args.output, args.seed, args.worlds)
        print(args.output.resolve())
    else:
        print(json.dumps(grade(args.dataset, args.family, args.sql.read_text()), indent=2))
