"""Design and review a new domain in separate, sequential Pi sessions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
import os
from tempfile import TemporaryDirectory
from pathlib import Path
import re
import sqlite3
import subprocess


INKLING = "thinkingmachines/inkling-2-small:free"


def ask(prompt, model=None, files=None):
    with TemporaryDirectory() as tmp:
        env = os.environ.copy()
        args = ["pi", "--no-session", "--no-extensions", "--no-context-files", "--no-skills"]
        if model == INKLING:
            config = {"providers":{"openrouter":{"baseUrl":"https://openrouter.ai/api/v1",
                      "api":"openai-completions","apiKey":"$OPENROUTER_API_KEY",
                      "models":[{"id":model,"contextWindow":1048576,"maxTokens":32768}]}}}
            Path(tmp,"models.json").write_text(json.dumps(config))
            env["PI_CODING_AGENT_DIR"] = tmp
            args += ["--provider","openrouter","--model",model,"--thinking","low"]
        elif model:
            args += ["--model",model]
        work = Path(tmp,"work")
        work.mkdir()
        instruction = ("Use write to create these files: " + ", ".join(files.values()) + ". " if files else
                       "Use write to save the requested JSON object as result.json in the current directory. ")
        reply = subprocess.run(args + ["--tools","read,write,edit","--mode","json","--print",
            instruction + prompt],
            cwd=work, env=env, stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=1200)
        if reply.returncode:
            detail = (reply.stderr.strip() or reply.stdout.strip() or "No diagnostic from Pi")[-1500:]
            raise SystemExit(f"Pi exited {reply.returncode}: {detail}")
        final = ""
        stop = "unknown"
        for line in reply.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            msg = event.get("message",{})
            if event.get("type") == "message_end" and msg.get("role") == "assistant":
                stop = msg.get("stopReason", "unknown")
                if stop in ("error","aborted"):
                    raise SystemExit(f"Pi {stop}: {msg.get('errorMessage','unknown error')}")
                final = "".join(block.get("text","") for block in msg.get("content",[]) if block.get("type")=="text")
        if files and all((work/name).is_file() and (work/name).stat().st_size for name in files.values()):
            return {key:(work/name).read_text() for key,name in files.items()}
        result = work/"result.json"
        try:
            return json.loads(result.read_text() if result.is_file() else final)
        except ValueError as exc:
            raise SystemExit(f"Pi returned no valid artifact (stop reason {stop}): {exc}") from exc


SKILL = Path(__file__).parent / ".agents/skills/text2sql-domain-review/SKILL.md"


def target_questions(brief):
    targets = {}
    for qid, question in re.findall(r"^ *(?:- )?\[(Q[0-9]+)\] *(.+)$", brief, re.MULTILINE):
        if qid in targets:
            raise ValueError(f"Duplicate brief ID {qid}")
        ordered = question.startswith("[ordered] ")
        text = question.removeprefix("[ordered] ").strip()
        if not text:
            raise ValueError(f"Empty target question {qid}")
        targets[qid] = {"question": text, "ordered": ordered}
    if not targets:
        raise ValueError("List the brief's target questions as [Q1] Question text, one per line.")
    return targets


def verify(schema, review, targets):
    checks = review["checks"]
    if sorted(c["id"] for c in checks) != sorted(targets):
        raise ValueError("Review must cover each brief ID exactly once")
    for check in checks:
        if check["question"] != targets[check["id"]]["question"]:
            raise ValueError(f"Question changed for {check['id']}")
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(schema)
        tables = db.execute("SELECT count(*) FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        if not 10 <= tables <= 40:
            raise ValueError(f"Found {tables} domain tables")
        db.executescript(review["fixture_sql"])
        if db.execute("PRAGMA foreign_keys").fetchone() != (1,) or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign-key validation failed")
        if not review["checks"] or not review["invalid_inserts"]:
            raise ValueError("Reviewer must supply positive and negative checks")
        for probe in review["invalid_inserts"]:
            sql = probe["sql"]
            try:
                db.execute(sql)
            except sqlite3.IntegrityError as exc:
                if exc.sqlite_errorname == probe["constraint"] == "SQLITE_CONSTRAINT_FOREIGNKEY":
                    continue
                raise ValueError(f"Unexpected constraint: {exc.sqlite_errorname}") from exc
            raise ValueError(f"Constraint failed to reject {sql}")
        db.execute("PRAGMA query_only=ON")
        for check in review["checks"]:
            def compare_rows(values):
                rows = list(map(tuple, values))
                return rows if targets[check["id"]]["ordered"] else sorted(rows, key=repr)

            rows = compare_rows(check["rows"])
            gold = db.execute(check["sql"])
            width = len(gold.description)
            if compare_rows(gold) != rows:
                raise ValueError(check["question"])
            wrong = db.execute(check["wrong_sql"])
            if len(wrong.description) != width or not check["witness"].strip():
                raise ValueError("Counterexample requires matching columns and a fixture witness")
            if compare_rows(wrong) == rows:
                raise ValueError("Fixture misses wrong query: " + check["question"])


def review_design(folder, brief, schema, targets, rules, model):
    context = f"{brief}\nReview rules: {rules}\nFrozen SQLite DDL:\n{schema}"
    fp = folder/"fixture.sql"
    if not fp.exists():
        fixture = ask("Write only fixture.sql. Compact synthetic INSERTs testing the cases in the brief. Use a recursive CTE or multirow inserts for repeated cases. Do not write any queries yet. " + context,
                      model, {"fixture":"fixture.sql"})["fixture"]
        fp.write_text(fixture)
    fixture = fp.read_text()
    context += "\nFrozen fixture:\n" + fixture
    checks = []
    probes = []
    findings = []
    def one(item):
        qid, target = item
        path = folder/f"check-{qid}.json"
        print(f"Reviewing {qid}", flush=True)
        if path.exists():
            part = json.loads(path.read_text())
        else:
            part = ask(f"""Review ONLY {qid}: {target['question']}. Return object with check, findings
(array of blocking issues), and invalid_inserts (array, use an invalid FK INSERT that fails specifically
with SQLITE_CONSTRAINT_FOREIGNKEY, as objects with sql and constraint). check must have id,
question (verbatim), sql, rows (literal arrays derived by hand), wrong_sql and witness.
Use the frozen fixture as is. Ordered={target['ordered']}. Write result.json early.
{context}""", model)
            path.write_text(json.dumps(part, indent=2))
        return part

    with ThreadPoolExecutor(max_workers=3) as pool:
        for part in pool.map(one, targets.items()):
            checks.append(part["check"])
            probes.extend(part["invalid_inserts"])
            findings.extend(part["findings"])
    return dict(checks=checks, findings=findings, invalid_inserts=probes, fixture_sql=fixture)


def design(brief, output, rounds, model=None):
    targets = target_questions(brief)
    rules = SKILL.read_text()
    output.mkdir(parents=True, exist_ok=True)
    identity = {"brief_sha256": hashlib.sha256(brief.encode()).hexdigest(), "model": model}
    marker = output/"run.json"
    if marker.exists() and json.loads(marker.read_text()) != identity:
        raise SystemExit("Output belongs to another brief or model. Choose a new directory.")
    if not marker.exists():
        if any(p.is_file() for p in output.rglob("*")):
            raise SystemExit("Existing untracked design artifacts; choose a new output directory.")
        marker.write_text(json.dumps(identity))
    if (output/"accepted.json").exists():
        print(output/"accepted.json")
        return
    feedback = ""
    for number in range(1, rounds+1):
        folder = output / f"round-{number}"
        folder.mkdir(exist_ok=True)
        print(f"Round {number}: author", flush=True)
        checkpoint = folder/"author.json"
        author = json.loads(checkpoint.read_text()) if checkpoint.exists() else ask(f"""You author SQLite domain designs. Write schema.sql and DOMAIN.md in the current directory. Implement 10-40 domain tables. Document grain, keys, relationships,
assumptions and questions. Use only SQLite DDL. Brief: {brief}
Project rules: {rules}
Previous design, reviewer findings, and execution feedback: {feedback}""", model, {"schema_sql":"schema.sql","domain_markdown":"DOMAIN.md"})
        checkpoint.write_text(json.dumps(author, indent=2))
        schema = author["schema_sql"]
        (folder/"schema.sql").write_text(schema)
        (folder/"DOMAIN.md").write_text(author["domain_markdown"])
        print(f"Round {number}: reviewer", flush=True)
        saved_review = folder/"review.json"
        review = json.loads(saved_review.read_text()) if saved_review.exists() else review_design(folder, brief, schema, targets, rules, model)
        (folder/"review.json").write_text(json.dumps(review, indent=2))
        try:
            if review["findings"] != []:
                raise ValueError(str(review["findings"]))
            verify(schema, review, targets)
        except (ValueError, sqlite3.Error, KeyError, TypeError) as exc:
            (folder/"findings.txt").write_text(str(exc))
            feedback = json.dumps([author, review, str(exc)])
            continue
        proof = {"round": number, "question_ids": list(targets), "schema_sha256": hashlib.sha256(schema.encode()).hexdigest()}
        (output/"accepted.json").write_text(json.dumps(proof, indent=2))
        print(output/"accepted.json", flush=True)
        return
    raise SystemExit("Unresolved review. Inspect the final round's findings.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path)
    parser.add_argument("new_directory", type=Path)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--model", default=INKLING, help="Pi model ID (defaults to OpenRouter Inkling free)")
    args = parser.parse_args()
    design(args.brief.read_text(), args.new_directory, args.rounds, args.model)
