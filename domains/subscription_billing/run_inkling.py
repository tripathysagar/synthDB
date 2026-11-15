import argparse
import json
import hashlib
import shutil
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
MODEL = "thinkingmachines/inkling-2-small:free"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["author", "reviewer", "generator", "fixture", "checks"])
    parser.add_argument("feedback", nargs="?", default="")
    args = parser.parse_args()
    instructions = {
        "fixture": "Create fixture.sql containing ONLY synthetic INSERTs. Design a small hand-verifiable scenario for the six question IDs. Include a third-place tie, a payment split between two invoices, balance changes across March and April cutoffs, a void invoice with March credit, and a zero-activity customer. Ensure dates and amounts are valid. Write the file first. No queries needed.",
        "checks": "Read fixture.sql and schema.sql. Only handle the question IDs in the last instruction. For these IDs write checks-<first ID>.json, a JSON array of objects each with id, verbatim question (omit [ordered]), sql, rows (hand-calculated literal arrays), wrong_sql (same-shape query with one plausible wrong assumption), witness. No other output files.",
        "author": "Write schema.sql and DOMAIN.md here. Build a compact ten-to-twelve table schema for the brief. Use composite foreign keys to enforce customer ownership. Document business rules.",
        "reviewer": "Read schema.sql and brief.md. Write review.json matching the verify() contract in the supplied project verifier. Include literal expected rows for all six questions and witnesses on a single synthetic fixture. Use SQLite syntax. Record findings as an array. Do not edit schema or brief.",
        "generator": "Read schema.sql, brief.md and review.json. Write generator.py implementing populate(db,seed) returning a dict keyed Q1 through Q6 of expected row tuples computed from events independently in Python, while inserting all rows into db. Generate seeded Faker data, multiple randomized IDs, ranking ties, realistic allocation and settlement dates; make world answers vary. Leave export to caller."
    }
    outputs = {"author":["schema.sql","DOMAIN.md"],"fixture":["fixture.sql"],
               "reviewer":["review.json"],"generator":["generator.py"]}
    if args.role=="checks":
        first = args.feedback.split()[0]
        if first not in {"Q1","Q3","Q5"}:
            parser.error("Start batch instructions with Q1, Q3 or Q5.")
        outputs["checks"] = [f"checks-{first}.json"]
    required = outputs[args.role]
    prompt = instructions[args.role] + "\n" + (ROOT/"brief.md").read_text() + "\n" + (ROOT.parents[1]/".agents/skills/text2sql-domain-review/SKILL.md").read_text()
    if args.role == "reviewer":
        prompt += "\n" + (ROOT.parents[1]/"pi_design.py").read_text()
    prompt += "\n" + args.feedback
    with TemporaryDirectory() as tmp:
        work = Path(tmp)/"work"
        work.mkdir()
        for name in ("brief.md","schema.sql","DOMAIN.md","fixture.sql","review.json",*required):
            src = ROOT/name
            if src.is_file():
                shutil.copyfile(src, work/name)
        model = {"id":MODEL, "contextWindow":1048576, "maxTokens":32768}
        config = {"providers":{"openrouter":{"baseUrl":"https://openrouter.ai/api/v1","api":"openai-completions","apiKey":"$OPENROUTER_API_KEY","models":[model]}}}
        Path(tmp,"models.json").write_text(json.dumps(config))
        env = {**os.environ,"PI_CODING_AGENT_DIR":tmp}
        cmd = ["pi","--provider","openrouter","--model",MODEL,"--no-session","--no-extensions","--no-context-files","--no-skills","--tools","read,write,edit","--mode","json","--print",prompt]
        result = subprocess.run(cmd, cwd=work,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=1200)
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "message_end":
                msg = event.get("message",{})
                if msg.get("role")=="assistant":
                    print("Pi:",msg.get("model"),msg.get("stopReason"),(msg.get("errorMessage") or "")[:300],[(b.get("type"),b.get("name")) for b in msg.get("content",[]) if isinstance(b,dict)],flush=True)
                    if msg.get("stopReason") in ("error","aborted"):
                        raise RuntimeError("Model request failed")
        result.check_returncode()
        saved = {}
        for name in required:
            src = work/name
            if not src.is_file() or not src.stat().st_size:
                raise RuntimeError(f"Pi returned without producing {name}")
            if name.endswith(".json"):
                json.loads(src.read_text())
            saved[name] = hashlib.sha256(src.read_bytes()).hexdigest()
        for name in required:
            stage = ROOT/(name+".new")
            shutil.copyfile(work/name, stage)
            stage.replace(ROOT/name)
        with (ROOT/"stages.jsonl").open("a") as journal:
            print(json.dumps({"role":args.role,"model":MODEL,"outputs":saved}),file=journal)


if __name__ == "__main__":
    main()
