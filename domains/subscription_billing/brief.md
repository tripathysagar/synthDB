# SaaS subscription billing

Design 10-40 related SQLite tables for subscriptions, invoices and line items, payments and allocations, and credits. Document table grain and foreign keys. All amounts are integer USD cents. Use synthetic data only. An issued invoice amount is the sum of its lines. A successful payment reduces an invoice balance only by the amount allocated to it, effective on the allocation date. An applied credit reduces the balance on its application date. Cutoffs are inclusive UTC calendar dates. Exclude void invoices from balances; do not over-allocate. One payment can settle multiple invoices belonging to the same customer.

[Q1] For each issued, nonvoid invoice outstanding on 2026-03-31, return its ID and positive balance in cents as of that date.
[Q2] Which payment IDs were successfully allocated to at least two distinct invoices by 2026-03-31?
[Q3] Return every customer ID and its total cents of credits applied to nonvoid invoices during March 2026, including zero.
[Q4] Which distinct subscription IDs have at least one nonvoid invoice issued in March 2026 with two or more line items?
[Q5] [ordered] Return the three customers with the highest positive outstanding balances on 2026-03-31, as customer ID and balance in cents, descending by balance then ascending by ID.
[Q6] Which nonvoid invoice IDs had a positive balance on 2026-03-31 and were fully settled by 2026-04-30?

Generate nine seeded Faker worlds across train, validation and test. Keep question families in a single split. Include partial payments on either side of a cutoff, split allocations, credits, zero activity and ranking ties. Verify literal reviewer fixtures and expected answers derived independently from generated events. Export SQLite, solver prompts, separate answer JSONL, and a run manifest recording the exact model and checks.
