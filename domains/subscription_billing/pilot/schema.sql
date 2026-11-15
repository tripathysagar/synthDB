PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE CHECK (instr(email, '@') > 1)
) STRICT;

CREATE TABLE plans (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    billing_interval TEXT NOT NULL CHECK (billing_interval IN ('month', 'year')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0)
) STRICT;

CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    status TEXT NOT NULL CHECK (status IN ('active', 'canceled')),
    started_on TEXT NOT NULL CHECK (strftime('%Y-%m-%d', started_on, '+0 days') IS started_on),
    canceled_on TEXT CHECK (canceled_on IS NULL OR strftime('%Y-%m-%d', canceled_on, '+0 days') IS canceled_on),
    UNIQUE (id, customer_id),
    CHECK (canceled_on IS NULL OR canceled_on >= started_on),
    CHECK ((status = 'canceled') = (canceled_on IS NOT NULL))
) STRICT;

CREATE TABLE subscription_events (
    id INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('started', 'plan_changed', 'paused', 'resumed', 'canceled')),
    occurred_on TEXT NOT NULL CHECK (strftime('%Y-%m-%d', occurred_on, '+0 days') IS occurred_on),
    FOREIGN KEY (subscription_id, customer_id) REFERENCES subscriptions(id, customer_id),
    UNIQUE (subscription_id, occurred_on, event)
) STRICT;

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    subscription_id INTEGER NOT NULL,
    issued_on TEXT NOT NULL CHECK (strftime('%Y-%m-%d', issued_on, '+0 days') IS issued_on),
    due_on TEXT NOT NULL CHECK (strftime('%Y-%m-%d', due_on, '+0 days') IS due_on),
    status TEXT NOT NULL CHECK (status IN ('issued', 'void')),
    FOREIGN KEY (subscription_id, customer_id) REFERENCES subscriptions(id, customer_id),
    CHECK (due_on >= issued_on),
    UNIQUE (id, customer_id)
) STRICT;

CREATE TABLE invoice_lines (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0)
) STRICT;

CREATE TABLE payment_methods (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    brand TEXT NOT NULL CHECK (brand IN ('visa', 'mastercard', 'amex', 'discover')),
    last4 TEXT NOT NULL CHECK (length(last4) = 4 AND last4 NOT GLOB '*[^0-9]*'),
    UNIQUE (id, customer_id)
) STRICT;

CREATE TABLE payments (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    payment_method_id INTEGER NOT NULL,
    received_on TEXT NOT NULL CHECK (strftime('%Y-%m-%d', received_on, '+0 days') IS received_on),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    FOREIGN KEY (payment_method_id, customer_id) REFERENCES payment_methods(id, customer_id),
    UNIQUE (id, customer_id)
) STRICT;

CREATE TABLE payment_allocations (
    id INTEGER PRIMARY KEY,
    payment_id INTEGER NOT NULL,
    invoice_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    allocated_on TEXT NOT NULL CHECK (strftime('%Y-%m-%d', allocated_on, '+0 days') IS allocated_on),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    FOREIGN KEY (payment_id, customer_id) REFERENCES payments(id, customer_id),
    FOREIGN KEY (invoice_id, customer_id) REFERENCES invoices(id, customer_id),
    UNIQUE (payment_id, invoice_id)
) STRICT;

CREATE TABLE credits (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    issued_on TEXT NOT NULL CHECK (strftime('%Y-%m-%d', issued_on, '+0 days') IS issued_on),
    reason TEXT NOT NULL CHECK (reason IN ('refund', 'adjustment', 'billing_error', 'promo')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    UNIQUE (id, customer_id)
) STRICT;

CREATE TABLE credit_applications (
    id INTEGER PRIMARY KEY,
    credit_id INTEGER NOT NULL,
    invoice_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    applied_on TEXT NOT NULL CHECK (strftime('%Y-%m-%d', applied_on, '+0 days') IS applied_on),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    FOREIGN KEY (credit_id, customer_id) REFERENCES credits(id, customer_id),
    FOREIGN KEY (invoice_id, customer_id) REFERENCES invoices(id, customer_id),
    UNIQUE (credit_id, invoice_id)
) STRICT;

CREATE INDEX subscription_events_by_subscription ON subscription_events(subscription_id);
CREATE INDEX invoice_lines_by_invoice ON invoice_lines(invoice_id);
CREATE INDEX invoices_by_customer ON invoices(customer_id, issued_on);
CREATE INDEX payments_by_customer ON payments(customer_id, received_on);
CREATE INDEX payment_allocations_by_invoice ON payment_allocations(invoice_id, allocated_on);
CREATE INDEX payment_allocations_by_payment ON payment_allocations(payment_id);
CREATE INDEX credit_applications_by_invoice ON credit_applications(invoice_id, applied_on);
CREATE INDEX credit_applications_by_credit ON credit_applications(credit_id);
