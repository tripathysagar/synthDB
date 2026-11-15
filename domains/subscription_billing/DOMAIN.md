# SaaS subscription billing

Build an analytical snapshot of a synthetic SaaS billing system: plans and subscriptions, invoices with line items, payments with allocations, and credit memos with applications. All amounts are integer USD cents. All dates are UTC calendar dates in `YYYY-MM-DD` format. Cutoffs are **inclusive**. The scope covers customer subscription state, invoicing, cash application and credits. Taxes, FX, dunning, refunds as cash-out, and failed-payment retry history fall outside this snapshot. All data is synthetic; no real customer or payment data appears.

## Schema and foreign keys

Every listed column is required unless marked otherwise. Surrogate IDs are unique integers. Each foreign key below references a primary key and permits many child rows per parent. A parent may have zero child rows. The SQLite DDL defines the exact types, checks and keys. Eleven tables:

| Table | One row represents | Columns and relationships |
| --- | --- | --- |
| customers | One synthetic customer | id (PK), name, email (unique) |
| plans | One billable plan | id (PK), name (unique), billing_interval ('month' or 'year'), amount_cents |
| subscriptions | One customer's subscription to a plan | id (PK), customer_id → customers.id, plan_id → plans.id, status ('active' or 'canceled'), started_on, canceled_on (NULL iff active). UNIQUE (id, customer_id). The composite key lets children pin the subscription's owner. |
| subscription_events | One lifecycle event on a subscription | (subscription_id, customer_id) → subscriptions(id, customer_id), event ('started', 'plan_changed', 'paused', 'resumed', 'canceled'), occurred_on. The customer_id must equal the subscription's owner. |
| invoices | One invoice issued to a customer for a subscription | (subscription_id, customer_id) → subscriptions(id, customer_id), issued_on, due_on (≥ issued_on), status ('issued' or 'void'). UNIQUE (id, customer_id). The composite key pins the invoice to the subscription's owner. |
| invoice_lines | One billed line on an invoice | invoice_id → invoices.id, description, amount_cents (> 0). Lines carry no customer column; ownership flows through the invoice. |
| payment_methods | One synthetic payment method on file | id (PK), customer_id → customers.id, brand, last4. UNIQUE (id, customer_id). |
| payments | One payment attempt received from a customer | (payment_method_id, customer_id) → payment_methods(id, customer_id), received_on, amount_cents (> 0), status ('succeeded' or 'failed'). UNIQUE (id, customer_id). The composite key pins the method to the payer. |
| payment_allocations | One allocation of a payment to an invoice, effective on allocated_on | (payment_id, customer_id) → payments(id, customer_id), (invoice_id, customer_id) → invoices(id, customer_id), allocated_on, amount_cents (> 0). Both composites must agree on customer_id, so a payment can never be applied to another customer's invoice. UNIQUE (payment_id, invoice_id): at most one allocation per payment–invoice pair. |
| credits | One credit memo granted to a customer | id (PK), customer_id → customers.id, issued_on, reason, amount_cents (> 0). UNIQUE (id, customer_id). |
| credit_applications | One application of a credit to an invoice, effective on applied_on | (credit_id, customer_id) → credits(id, customer_id), (invoice_id, customer_id) → invoices(id, customer_id), applied_on, amount_cents (> 0). UNIQUE (credit_id, invoice_id). The composites pin the credit and the invoice to the same owner. |

The customer-ownership rule is enforced structurally by composite foreign keys, not by convention: subscription_events → subscriptions, invoices → subscriptions, payments → payment_methods, payment_allocations → payments and invoices, credit_applications → credits and invoices. An allocation pairing customer A's payment with customer B's invoice violates the referenced (id, customer_id) unique key and is rejected by SQLite.

## Dates, amounts and balances

- All dates are UTC calendar dates (`YYYY-MM-DD`). Every cutoff is inclusive: an allocation on 2026-03-31 counts toward a 2026-03-31 cutoff; one dated 2026-04-01 does not. Date checks reject rollover inputs such as `2026-02-31` because SQLite normalizes them to a different calendar day.
- Amounts are integer USD cents everywhere. No floating point is used or implied.
- An issued invoice amount is never stored; it is the sum of its lines: `SUM(invoice_lines.amount_cents)` over the invoice. Lines are positive cents only; discounts and concessions are modeled as credits, never as negative lines.
- Void invoices are retained with status `'void'` but are excluded from every balance computation and from every question below. Allocations and credit applications pointing at a void invoice remain as rows; the invoice simply drops out of all balances. The void cannot be reversed by any allocation or credit.
- Only allocations whose payment has status `'succeeded'` reduce a balance. Failed payments never reduce a balance. The generator creates allocations only for succeeded payments, and the balance definition joins `succeeded` explicitly so a stray allocation against a failed payment is inert.
- The **invoice balance as of inclusive date D** is:

  `balance(invoice, D) = SUM(lines) − SUM(allocations a JOIN payments p ON p.id = a.payment_id WHERE p.status = 'succeeded' AND a.allocated_on <= D) − SUM(credit_applications ca WHERE ca.applied_on <= D)`

- An invoice is **outstanding on D** when it is issued (nonvoid) and its balance on D is strictly positive.
- **A payment reduces an invoice only by the allocated amount, on the allocation date** — not on the receipt date. Unallocated payment remainder reduces nothing and belongs to the customer, not to an invoice.
- **A credit reduces an invoice only by the applied amount, on the application date.**
- **Do not over-allocate.** For every nonvoid invoice: allocations (succeeded payments) plus credit applications, summed over all time, never exceed the invoice total; the balance never goes negative. Per payment: allocations sum to at most the payment amount. Per credit: applications sum to at most the credit amount. These are aggregate rules SQLite CHECK constraints cannot express; they are enforced by the generator and must be verified independently by the review fixture. An invoice exactly settled (balance = 0) is settled, not over-allocated.
- One payment can settle multiple invoices. Every invoice a payment is allocated to must belong to that payment's customer (composite FK). An invoice can likewise be settled by several payments and several credits; only their dates and amounts matter, never an application order.
- Chronology: allocated_on ≥ payments.received_on; applied_on ≥ credits.issued_on; allocated_on / applied_on may be any date ≥ the invoice's issued_on. These cross-row and aggregate rules live in the generator and the review fixture, not in the DDL.
- subscription_events is an audit trail. subscriptions.status and canceled_on reflect the latest lifecycle event (started, canceled). The generator keeps them consistent; the DDL only pins ownership.
- A subscription's current status does not delete or hide its historical invoices. A canceled subscription's unpaid nonvoid invoices remain outstanding.

## Questions the snapshot must support

Frozen question IDs. For each: result grain, columns, duplicate handling, zero/cutoff rules, and ordering. Q1–Q4 and Q6 are unordered; the grader compares rows including multiplicity. Only Q5 is `[ordered]`.

1. **[Q1]** For each issued, nonvoid invoice outstanding on 2026-03-31, return its ID and positive balance in cents as of that date. Columns: `invoice_id, balance_cents`. One row per invoice; no duplicates. Balance > 0 strictly; void invoices and fully settled invoices are excluded. Cutoff 2026-03-31 inclusive.
2. **[Q2]** Which payment IDs were successfully allocated to at least two distinct invoices by 2026-03-31? Columns: `payment_id`. Succeeded payments only; distinct invoice count over allocations with allocated_on ≤ 2026-03-31 ≥ 2. One row per payment ID; unordered.
3. **[Q3]** Return every customer ID and its total cents of credits applied to nonvoid invoices during March 2026, including zero. Columns: `customer_id, credits_applied_cents`. One row per customer (all customers, even those with no invoices or no credits). applied_on between 2026-03-01 and 2026-03-31 inclusive; applications to void invoices excluded. Unapplied credits and applications before/after March 2026 do not count. Unordered.
4. **[Q4]** Which distinct subscription IDs have at least one nonvoid invoice issued in March 2026 with two or more line items? Columns: `subscription_id`. One row per subscription; duplicates removed by DISTINCT. Void invoices excluded; issued_on in March 2026 inclusive; line count ≥ 2 per single invoice. Unordered.
5. **[Q5] [ordered]** Return the three customers with the highest positive outstanding balances on 2026-03-31, as customer ID and balance in cents, descending by balance then ascending by ID. Columns: `customer_id, balance_cents`. Exactly three rows. Customer outstanding balance = sum of balances of that customer's issued nonvoid invoices on 2026-03-31. Only customers with balance > 0 are eligible. Ties on balance break by ascending customer_id. Unordered-by-implementation is wrong: the sort is contractual.
6. **[Q6]** Which nonvoid invoice IDs had a positive balance on 2026-03-31 and were fully settled by 2026-04-30? Columns: `invoice_id`. One row per invoice. Nonvoid; balance(2026-03-31) > 0; balance(2026-04-30) = 0; allocations and applications dated up to and including 2026-04-30 count. Unordered.

All amounts are cents; all IDs are integers. No question aggregates across currencies or mixes void invoices into a balance.

## Review scenarios

- **Crossing the cutoff with a partial payment.** Two succeeded payments allocate 4,000 cents to invoice I before the cutoff and 6,000 after 2026-03-31. Only the 4,000 reduces the balance as of 2026-03-31; Q1 reports the remainder. The gold SQL counts the allocation by `allocated_on`, not by `received_on`.
- **Split allocation across invoices of one customer.** One succeeded payment allocated to two invoices of the same customer qualifies the payment for Q2; each invoice's balance falls by its own allocation only. A payment allocated twice to the same invoice is impossible (UNIQUE payment_id, invoice_id).
- **Inclusive edge on the cutoff.** An allocation or credit application dated exactly 2026-03-31 counts for Q1/Q2/Q3/Q5; dated 2026-04-01 it counts only for Q6's settlement window. A credit applied 2026-04-15 settles an invoice for Q6 but contributes nothing to Q3.
- **Void exclusion.** A void invoice with two lines and a large balance contributes nothing to Q1/Q5/Q6; a credit applied to it in March 2026 contributes nothing to Q3; it does not satisfy Q4.
- **Failed payment.** A failed payment with no allocations leaves balances untouched. Balance logic joins `status = 'succeeded'` explicitly; a fixture that allocates a failed payment must show the balance unchanged.
- **Zero activity.** A brand-new customer with no invoices appears in Q3 with 0 and nowhere else. A customer whose invoices are all void or settled does not appear in Q5. Fewer than three customers with positive balances yields fewer than three rows for Q5 — the fixture must guarantee at least three.
- **Q5 ordering tie.** Two customers tie on balance at the third-place boundary. Correct order: higher balance first, then lower customer_id. A plausible wrong query (`ORDER BY balance DESC, customer_id DESC`, or bare `ORDER BY balance DESC`) reverses or leaves the tie arbitrary; the fixture must contain that exact tie so the wrong order is detectable.
- **Q6 boundary.** An invoice still outstanding on 2026-04-30 (positive balance) is excluded; an invoice whose final allocation lands exactly on 2026-04-30 is included.
- **Broken relationships to reject.** (a) payment from customer A allocated to invoice of customer B → composite FK mismatch, rejected; (b) payment method of customer B used on customer A's payment → rejected; (c) credit of customer B applied to customer A's invoice → rejected; (d) invoice for customer B issued against customer A's subscription → rejected; (e) duplicate allocation of one payment to one invoice → UNIQUE violation; (f) zero-cent line or allocation → CHECK violation; (g) `2026-02-31` date → CHECK violation via SQLite rollover normalization.
- **Over-allocation is out of DDL scope.** No CHECK enforces `sum(allocations + applications) ≤ invoice total`; the generator must never emit it, and the reviewer must hand-verify at least one fixture invoice settled exactly to zero and reject any generated row that would take a balance negative.

## Generation and verification notes

- Synthetic Faker data only; every name, email, plan name and description is invented.
- Nine seeded worlds across train, validation and test; question families stay in a single split; edge-case IDs vary across seeds.
- Expected answers are derived independently from generated events (allocate/apply/void), not from the reference SQL, and the reference queries are executed against every generated world before export.
- Report first-attempt passes separately from repaired answers; retain the manifest with the exact model ID, seed set, split assignment and check results.
- Cutoff semantics, void exclusion, succeeded-only reduction and no-over-allocation are the four assumptions a wrong-but-plausible alternative will get wrong; each review fixture must contain at least one fact that distinguishes the gold rule from that alternative, per the frozen table above.
