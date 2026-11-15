"""Seeded synthetic world generator for the SaaS subscription billing domain.

populate(db, seed) fills one world (seeded Faker) into the SQLite database and
returns the expected Q1..Q6 answer tuples, computed independently from the
recorded event rows (never via SQL). Export (SQLite file, prompts, JSONL,
manifest) is left to the caller. Date cutoffs are inclusive UTC calendar
dates; amounts are integer cents; void invoices are excluded from balances.
"""
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from faker import Faker

MAR_START, MAR, APR = '2026-03-01', '2026-03-31', '2026-04-30'


def _d(s):
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def populate(db, seed):
    close = isinstance(db, (str, Path))
    con = sqlite3.connect(str(db)) if close else db
    fake = Faker()
    fake.seed_instance(seed)
    rng = random.Random(seed)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'invoices' not in tables:
        con.executescript(Path(__file__).with_name('schema.sql').read_text())
    cur = con.cursor()

    used = set()

    def rid():
        while True:
            i = rng.randrange(1000, 90000)
            if i not in used:
                used.add(i)
                return i

    remaining = {}          # invoice_id -> unallocated cents (generation-time clamp)
    inv_recs, line_recs = [], []
    pay_recs, alloc_recs, app_recs = [], [], []
    customers = []
    payments = {}
    credits = {}
    invoice_dates = {}

    # --- plans (fixed catalogue) ---
    plan_ids = []
    for name, interval, amount in [('Basic', 'month', 2500), ('Pro', 'month', 5000), ('Basic Annual', 'year', 24000)]:
        pid = rid()
        plan_ids.append(pid)
        cur.execute('INSERT INTO plans VALUES (?,?,?,?)', (pid, name, interval, amount))

    # --- customers (Faker names, reserved example.com emails) ---
    for _ in range(rng.randrange(7, 11)):
        cid = rid()
        cur.execute('INSERT INTO customers VALUES (?,?,?)',
                    (cid, fake.name(), f'user{cid}@example.com'))
        customers.append(cid)
        cur.execute('INSERT INTO payment_methods VALUES (?,?,?,?)',
                    (rid(), cid, rng.choice(['visa', 'mastercard', 'amex', 'discover']),
                     f'{rng.randrange(10000):04d}'))

    # --- subscriptions (+ started events) ---
    subs = {}
    for cid in customers:
        sid = rid()
        started = f'2026-{"01"}-{rng.randrange(1, 28):02d}'
        cur.execute('INSERT INTO subscriptions VALUES (?,?,?,?,?,?)',
                    (sid, cid, rng.choice(plan_ids), 'active', started, None))
        cur.execute('INSERT INTO subscription_events VALUES (?,?,?,?,?)',
                    (rid(), sid, cid, 'started', started))
        subs[cid] = sid

    def make_invoice(cid, issued_on, status, lines):
        iid = rid()
        due = (_d(issued_on) + timedelta(days=30)).isoformat()
        cur.execute('INSERT INTO invoices VALUES (?,?,?,?,?,?)',
                    (iid, cid, subs[cid], issued_on, due, status))
        total = 0
        for desc, amount in lines:
            total += amount
            lid = rid()
            cur.execute('INSERT INTO invoice_lines VALUES (?,?,?,?)', (lid, iid, desc, amount))
            line_recs.append({'id': lid, 'invoice_id': iid})
        invoice_dates[iid] = issued_on
        remaining[iid] = total
        inv_recs.append({'id': iid, 'customer_id': cid, 'subscription_id': subs[cid],
                         'issued_on': issued_on, 'status': status, 'total': total})
        return iid

    def add_payment(cid, received_on, status, amount):
        pid = rid()
        pm = cur.execute('SELECT id FROM payment_methods WHERE customer_id=?', (cid,)).fetchone()[0]
        cur.execute('INSERT INTO payments VALUES (?,?,?,?,?,?)', (pid, cid, pm, received_on, amount, status))
        payments[pid] = (received_on, status, amount)
        pay_recs.append({'id': pid, 'customer_id': cid, 'status': status})
        return pid

    def add_allocation(pid, iid, cid, on, amount):
        received, status, available = payments[pid]
        on = max(on, received, invoice_dates[iid])
        amount = min(amount, available, remaining[iid])
        if amount <= 0:
            return 0
        payments[pid] = (received, status, available - amount)
        if status == 'succeeded':
            remaining[iid] -= amount
        cur.execute('INSERT INTO payment_allocations VALUES (?,?,?,?,?,?)',
                    (rid(), pid, iid, cid, on, amount))
        alloc_recs.append({'payment_id': pid, 'invoice_id': iid, 'allocated_on': on, 'amount_cents': amount})
        return amount

    def add_credit(cid, issued_on, reason):
        kid = rid()
        amount = 100 * rng.randrange(4, 30)
        cur.execute('INSERT INTO credits VALUES (?,?,?,?,?)', (kid, cid, issued_on, reason, amount))
        credits[kid] = (issued_on, amount)
        return kid, amount

    def add_application(kid, iid, cid, on, amount):
        issued, available = credits[kid]
        on = max(on, issued, invoice_dates[iid])
        amount = min(amount, available, remaining[iid])
        credits[kid] = (issued, available - amount)
        if amount <= 0:
            return 0
        remaining[iid] -= amount
        cur.execute('INSERT INTO credit_applications VALUES (?,?,?,?,?,?)',
                    (rid(), kid, iid, cid, on, amount))
        app_recs.append({'credit_id': kid, 'invoice_id': iid, 'customer_id': cid,
                         'applied_on': on, 'amount_cents': amount})
        return amount

    t2 = lambda lo, hi: 100 * rng.randrange(lo, hi)

    # --- tie customers (indices 0,1): identical invoice totals, zero activity ---
    tie_total = 100 * rng.randrange(80, 110)
    for i in (0, 1):
        issued = f'2026-03-{rng.randrange(4, 27):02d}'
        l1 = 100 * rng.randrange(20, tie_total // 100 - 5)
        make_invoice(customers[i], issued, 'issued',
                     [('Pro plan March', l1), ('Usage overage', tie_total - l1)])

    # --- cust2: split succeeded payment across two invoices (pre-cutoff) + March credit ---
    c2 = customers[2]
    sp_day = 31 if seed % 3 == 2 else rng.randrange(20, 29)
    sp_date = f'2026-03-{sp_day:02d}'
    invA_total = t2(45, 75)
    invA = make_invoice(c2, f'2026-03-{rng.randrange(4, 10):02d}', 'issued',
                        [('Pro plan March', invA_total - 1500), ('Extra seat license', 1500)])
    invB = make_invoice(c2, f'2026-03-{rng.randrange(10, 16):02d}', 'issued',
                        [('Basic plan March', 2500)])
    k2, _ = add_credit(c2, f'2026-03-{rng.randrange(12, 18):02d}', rng.choice(['promo', 'adjustment']))
    add_application(k2, invA, c2, f'2026-03-{rng.randrange(16, 25):02d}', t2(4, 9))
    aA, aB = t2(15, 30), t2(8, 20)
    sp = add_payment(c2, sp_date, 'succeeded', aA + aB)
    add_allocation(sp, invA, c2, sp_date, aA)
    add_allocation(sp, invB, c2, sp_date, aB)

    # --- cust3: void invoice (with inert credit) + April-30 settlement invoice ---
    c3 = customers[3]
    void_inv = make_invoice(c3, f'2026-03-{rng.randrange(10, 20):02d}', 'void',
                            [('Pro plan March duplicate', t2(40, 90))])
    kv, _ = add_credit(c3, f'2026-03-{rng.randrange(8, 12):02d}', 'billing_error')
    add_application(kv, void_inv, c3, f'2026-03-{rng.randrange(13, 18):02d}', t2(10, 15))
    invF = make_invoice(c3, f'2026-03-{rng.randrange(16, 23):02d}', 'issued',
                        [('Pro plan March', t2(30, 50)), ('Priority support', t2(15, 30))])
    part_amount = t2(10, 20)
    part_date = f'2026-03-{rng.randrange(26, 29):02d}'
    f_part = add_payment(c3, part_date, 'succeeded', part_amount)
    add_allocation(f_part, invF, c3, part_date, part_amount)

    # --- cust4: settled-before-cutoff invoice + unpaid multi-line invoice (failed payment) ---
    c4 = customers[4]
    g_total = t2(40, 70)
    invG = make_invoice(c4, f'2026-02-{rng.randrange(10, 28):02d}', 'issued',
                        [('Pro plan February', g_total)])
    g_pay = add_payment(c4, f'2026-03-{rng.randrange(10, 21):02d}', 'succeeded', g_total)
    add_allocation(g_pay, invG, c4, f'2026-03-{rng.randrange(10, 21):02d}', g_total)
    invH = make_invoice(c4, f'2026-03-{rng.randrange(18, 26):02d}', 'issued',
                        [('Basic plan March', t2(8, 30)), ('Usage overage', t2(5, 20))])
    fp_amt = t2(2, 6)
    fp = add_payment(c4, f'2026-03-{rng.randrange(20, 28):02d}', 'failed', fp_amt)
    add_allocation(fp, invH, c4, f'2026-03-{rng.randrange(20, 28):02d}', fp_amt)  # inert: failed

    # --- cust5: partial April split payment + March credit + April-only invoice ---
    c5 = customers[5]
    invI = make_invoice(c5, f'2026-03-{rng.randrange(20, 25):02d}', 'issued',
                        [('Pro plan March', t2(45, 60)), ('Extra storage add-on', t2(20, 35))])
    k5, _ = add_credit(c5, f'2026-03-{rng.randrange(24, 27):02d}', 'promo')
    add_application(k5, invI, c5, f'2026-03-{rng.randrange(27, 29):02d}', t2(6, 12))
    invJ = make_invoice(c5, f'2026-04-{rng.randrange(5, 16):02d}', 'issued',
                        [('Pro plan April', t2(45, 60))])  # April-only: invisible on 2026-03-31

    # --- April 5 split payment (misses Q2 cutoff) + April-12 credit + April-30 F settlement ---
    lp_i, lp_f = t2(20, 35), t2(5, 12)
    lp = add_payment(c5, '2026-04-05', 'succeeded', lp_i + lp_f)
    add_allocation(lp, invI, c5, '2026-04-05', lp_i)
    add_allocation(lp, invJ, c5, max('2026-04-05', invoice_dates[invJ]), lp_f)
    k5b, kb_amt = add_credit(c5, '2026-04-10', 'adjustment')
    add_application(k5b, invI, c5, '2026-04-12', min(700, kb_amt))
    f_final = remaining[invF]
    fin = add_payment(c3, APR, 'succeeded', f_final)  # April-30 full settlement
    add_allocation(fin, invF, c3, APR, f_final)
    assert remaining[invF] == 0

    # --- filler invoices (varied cardinality per seed) ---
    for _ in range(rng.randrange(0, 3)):
        cid = rng.choice(customers[2:6])
        fill_total = t2(15, 60)
        fill = make_invoice(cid, f'2026-02-{rng.randrange(10, 27):02d}', 'issued',
                            [('Pro plan February', fill_total)] if rng.random() < 0.5 else
                            [('Basic plan February', fill_total // 2), ('Usage overage', fill_total - fill_total // 2)])
        fate = rng.choice(['unpaid', 'settled_before', 'partial_before'])
        if fate == 'settled_before':
            p = add_payment(cid, f'2026-03-{rng.randrange(5, 26):02d}', 'succeeded', fill_total)
            add_allocation(p, fill, cid, f'2026-03-{rng.randrange(5, 26):02d}', fill_total)
        elif fate == 'partial_before':
            amt = max(100, int(fill_total * rng.randrange(40, 70) / 100))
            p = add_payment(cid, f'2026-03-{rng.randrange(5, 26):02d}', 'succeeded', amt)
            add_allocation(p, fill, cid, f'2026-03-{rng.randrange(5, 26):02d}', amt)

    for r in inv_recs:
        r['line_count'] = sum(1 for l in line_recs if l['invoice_id'] == r['id'])
    for r in inv_recs:
        assert remaining[r['id']] >= 0
    con.commit()

    # ================= independent answer derivation =================
    succ = {p['id'] for p in pay_recs if p['status'] == 'succeeded'}
    nonvoid = {r['id'] for r in inv_recs if r['status'] != 'void'}

    def balance(iid, cutoff):
        r = next(r for r in inv_recs if r['id'] == iid)
        a = sum(x['amount_cents'] for x in alloc_recs
                if x['invoice_id'] == iid and x['payment_id'] in succ and x['allocated_on'] <= cutoff)
        c = sum(x['amount_cents'] for x in app_recs
                if x['invoice_id'] == iid and x['applied_on'] <= cutoff)
        return r['total'] - a - c

    outstanding = [r for r in inv_recs
                   if r['status'] == 'issued' and r['issued_on'] <= MAR]

    q1 = sorted(((r['id'], balance(r['id'], MAR)) for r in outstanding),
                key=lambda t: t[0])
    q1 = [t for t in q1 if t[1] > 0]

    q2 = []
    for pid in sorted(succ):
        invs = {x['invoice_id'] for x in alloc_recs
                if x['payment_id'] == pid and x['allocated_on'] <= MAR}
        if len(invs) >= 2:
            q2.append((pid,))

    q3 = []
    for cid in sorted(customers):
        total = sum(x['amount_cents'] for x in app_recs
                    if x['customer_id'] == cid and MAR_START <= x['applied_on'] <= MAR
                    and x['invoice_id'] in nonvoid)
        q3.append((cid, total))

    q4 = sorted({r['subscription_id'] for r in inv_recs
                 if r['status'] != 'void' and MAR_START <= r['issued_on'] <= MAR
                 and r['line_count'] >= 2})
    q4 = [(s,) for s in q4]

    cust_bal = {}
    for r in outstanding:
        if r['id'] in nonvoid:
            cust_bal[r['customer_id']] = cust_bal.get(r['customer_id'], 0) + balance(r['id'], MAR)
    q5 = sorted(((c, b) for c, b in cust_bal.items() if b > 0),
                key=lambda t: (-t[1], t[0]))[:3]

    q6 = sorted(r['id'] for r in outstanding
                if r['id'] in nonvoid
                and balance(r['id'], MAR) > 0 and balance(r['id'], APR) == 0)
    q6 = [(i,) for i in q6]

    answers = {'Q1': q1, 'Q2': q2, 'Q3': q3, 'Q4': q4, 'Q5': q5, 'Q6': q6}
    if close:
        con.close()
    return answers
