"""Verify the Inkling review, generate nine worlds, then atomically publish the pilot."""
from collections import Counter
from contextlib import closing
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from pi_design import verify, target_questions
from run_inkling import MODEL


def accepted():
    ddl = (ROOT/"schema.sql").read_text()
    review = json.loads((ROOT/"review.json").read_text())
    targets = target_questions((ROOT/"brief.md").read_text())
    if review["findings"] != []:
        raise ValueError(review["findings"])
    verify(ddl, review, targets)
    return ddl, review, targets


def audit_ledger(db):
    checks = {
        "payment chronology": """SELECT a.id FROM payment_allocations a JOIN payments p ON p.id=a.payment_id
            JOIN invoices i ON i.id=a.invoice_id WHERE a.allocated_on < max(p.received_on,i.issued_on)""",
        "credit chronology": """SELECT a.id FROM credit_applications a JOIN credits c ON c.id=a.credit_id
            JOIN invoices i ON i.id=a.invoice_id WHERE a.applied_on < max(c.issued_on,i.issued_on)""",
        "payment over-allocation": """SELECT p.id FROM payments p JOIN payment_allocations a ON a.payment_id=p.id
            GROUP BY p.id HAVING sum(a.amount_cents)>p.amount_cents""",
        "credit over-application": """SELECT c.id FROM credits c JOIN credit_applications a ON a.credit_id=c.id
            GROUP BY c.id HAVING sum(a.amount_cents)>c.amount_cents""",
        "invoice over-settlement": """SELECT i.id FROM invoices i WHERE
            coalesce((SELECT sum(a.amount_cents) FROM payment_allocations a JOIN payments p ON p.id=a.payment_id
            WHERE a.invoice_id=i.id AND p.status='succeeded'),0) +
            coalesce((SELECT sum(a.amount_cents) FROM credit_applications a WHERE a.invoice_id=i.id),0)
            > (SELECT coalesce(sum(amount_cents),0) FROM invoice_lines WHERE invoice_id=i.id)""",
        "empty invoice": "SELECT i.id FROM invoices i WHERE NOT EXISTS(SELECT 1 FROM invoice_lines l WHERE l.invoice_id=i.id)",
    }
    for label, sql in checks.items():
        bad = db.execute(sql).fetchone()
        if bad:
            raise ValueError(f"{label} at row {bad}")


def assemble_review():
    checks = []
    for first in ("Q1","Q3","Q5"):
        checks.extend(json.loads((ROOT/f"checks-{first}.json").read_text()))
    fixture = (ROOT/"fixture.sql").read_text()
    review = {"findings": [], "fixture_sql": fixture, "checks": checks,
              "invalid_inserts": [{"sql": "INSERT INTO payment_allocations VALUES(999,101,3,1,'2026-03-31',1)",
                                   "constraint": "SQLITE_CONSTRAINT_FOREIGNKEY"}]}
    ddl = (ROOT/"schema.sql").read_text()
    verify(ddl,review,target_questions((ROOT/"brief.md").read_text()))
    with closing(sqlite3.connect(":memory:")) as db:
        db.executescript(ddl)
        db.executescript(fixture)
        audit_ledger(db)
    (ROOT/"review.json").write_text(json.dumps(review,indent=2))
    print("Six fixture checks accepted")


def build():
    from generator import populate
    ddl, review, targets = accepted()
    out = ROOT/"pilot"
    if out.exists():
        raise ValueError("Pilot already exists")
    with TemporaryDirectory(dir=ROOT) as tmp:
        stage = Path(tmp)/"pilot"
        stage.mkdir()
        (stage/"schema.sql").write_text(ddl)
        with closing(sqlite3.connect(stage/"review.sqlite")) as db:
            db.executescript(ddl)
            db.executescript(review["fixture_sql"])
            audit_ledger(db)
        report = []
        splits = {"train":{"Q1","Q2","Q4"},"validation":{"Q3"},"test":{"Q5","Q6"}}
        for index,(split,ids) in enumerate(splits.items()):
            folder = stage/split
            folder.mkdir()
            prompts, answers = [], []
            for offset in range(3):
                seed = 101 + index + 3*offset
                name = f"world-{seed}.sqlite"
                with closing(sqlite3.connect(folder/name)) as db:
                    db.execute("PRAGMA foreign_keys=ON")
                    db.executescript(ddl)
                    expected = populate(db,seed)
                    db.commit()
                    if db.execute("PRAGMA foreign_keys").fetchone() != (1,) or db.execute("PRAGMA foreign_key_check").fetchall() or db.execute("PRAGMA integrity_check").fetchone()!=("ok",):
                        raise ValueError(f"Integrity failure: {seed}")
                    audit_ledger(db)
                    if set(expected)!=set(targets):
                        raise ValueError("Generator oracle coverage mismatch")
                    for check in review["checks"]:
                        qid = check["id"]
                        rows = list(db.execute(check["sql"]))
                        oracle = list(map(tuple,expected[qid]))
                        match = rows==oracle if targets[qid]["ordered"] else Counter(rows)==Counter(oracle)
                        if not match:
                            raise ValueError(f"{seed} {qid}: SQL {rows} vs oracle {oracle}")
                        if qid in ids:
                            base = dict(id=f"{qid}-{seed}",family=qid,database=name)
                            prompts.append(dict(base,question=targets[qid]["question"]))
                            answers.append(dict(base,sql=check["sql"],rows=oracle))
                    report.append(dict(seed=seed,split=split,passed_question_ids=list(targets)))
            for filename, records in [("prompts",prompts),("answers",answers)]:
                (folder/f"{filename}.jsonl").write_text("".join(json.dumps(r)+"\n" for r in records))
        manifest = dict(revision_notes={"fixture_review_initial":"6/6 reference queries matched the initial reviewer fixture", "generated_world_initial":"blocked by cross-customer FK before scoring", "sql_repaired":["Q5","Q6"], "final_world_checks":len(report)*len(targets)},model=MODEL,schema_sha256=sha256(ddl.encode()).hexdigest(),worlds=report,faker=version("Faker"),sqlite=sqlite3.sqlite_version)
        (stage/"manifest.json").write_text(json.dumps(manifest,indent=2))
        stage.rename(out)


if __name__=="__main__":
    if sys.argv[1:]==["assemble"]:
        assemble_review()
    elif sys.argv[1:]==["review"]:
        accepted()
        print("Review passed")
    else:
        build()
