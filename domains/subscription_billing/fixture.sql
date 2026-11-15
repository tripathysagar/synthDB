INSERT INTO customers (id, name, email) VALUES
    (1, 'Ada Lovelace', 'ada@example.com'),
    (2, 'Ben Carter', 'ben@example.com'),
    (3, 'Cleo Diaz', 'cleo@example.com'),
    (4, 'Dan Ellis', 'dan@example.com'),
    (5, 'Eve Frost', 'eve@example.com');

INSERT INTO plans (id, name, billing_interval, amount_cents) VALUES
    (1, 'Basic', 'month', 2500),
    (2, 'Pro', 'month', 5000),
    (3, 'Basic Annual', 'year', 24000);

INSERT INTO subscriptions (id, customer_id, plan_id, status, started_on, canceled_on) VALUES
    (1, 1, 2, 'active', '2026-01-05', NULL),
    (2, 2, 2, 'active', '2026-01-10', NULL),
    (3, 3, 1, 'active', '2026-02-01', NULL),
    (4, 4, 2, 'active', '2026-02-15', NULL);

INSERT INTO subscription_events (id, subscription_id, customer_id, event, occurred_on) VALUES
    (1, 1, 1, 'started', '2026-01-05'),
    (2, 2, 2, 'started', '2026-01-10'),
    (3, 3, 3, 'started', '2026-02-01'),
    (4, 4, 4, 'started', '2026-02-15');

INSERT INTO invoices (id, customer_id, subscription_id, issued_on, due_on, status) VALUES
    (1, 1, 1, '2026-03-05', '2026-04-04', 'issued'),
    (2, 1, 1, '2026-03-20', '2026-04-19', 'issued'),
    (3, 2, 2, '2026-03-10', '2026-04-09', 'issued'),
    (4, 3, 3, '2026-03-25', '2026-04-24', 'issued'),
    (5, 4, 4, '2026-02-20', '2026-03-22', 'issued'),
    (6, 2, 2, '2026-03-15', '2026-04-14', 'void'),
    (7, 4, 4, '2026-03-28', '2026-04-27', 'issued'),
    (8, 3, 3, '2026-03-30', '2026-04-29', 'issued');

INSERT INTO invoice_lines (id, invoice_id, description, amount_cents) VALUES
    (1, 1, 'Pro plan March', 5000),
    (2, 1, 'Extra seat license', 1500),
    (3, 2, 'Additional storage add-on', 3000),
    (4, 3, 'Pro plan March', 4000),
    (5, 3, 'Onboarding fee', 4000),
    (6, 4, 'Basic plan March', 2500),
    (7, 5, 'Pro plan February', 6000),
    (8, 6, 'Pro plan March duplicate', 9000),
    (9, 7, 'Pro plan March', 4500),
    (10, 8, 'Basic plan March', 700),
    (11, 8, 'Usage overage', 500);

INSERT INTO payment_methods (id, customer_id, brand, last4) VALUES
    (1, 1, 'visa', '4242'),
    (2, 2, 'mastercard', '5454'),
    (3, 3, 'amex', '0005'),
    (4, 4, 'discover', '6011');

INSERT INTO payments (id, customer_id, payment_method_id, received_on, amount_cents, status) VALUES
    (101, 1, 1, '2026-03-25', 4800, 'succeeded'),
    (102, 2, 2, '2026-03-31', 3000, 'succeeded'),
    (103, 3, 3, '2026-04-10', 2500, 'succeeded'),
    (104, 4, 4, '2026-03-15', 2000, 'succeeded'),
    (105, 4, 4, '2026-04-05', 4000, 'succeeded'),
    (106, 2, 2, '2026-03-20', 8000, 'failed'),
    (107, 1, 1, '2026-04-15', 3500, 'succeeded');

INSERT INTO payment_allocations (id, payment_id, invoice_id, customer_id, allocated_on, amount_cents) VALUES
    (1, 101, 1, 1, '2026-03-25', 3000),
    (2, 101, 2, 1, '2026-03-25', 1800),
    (3, 102, 3, 2, '2026-03-31', 3000),
    (4, 103, 4, 3, '2026-04-10', 2500),
    (5, 104, 5, 4, '2026-03-15', 2000),
    (6, 105, 5, 4, '2026-04-05', 3000),
    (7, 105, 7, 4, '2026-04-05', 1000),
    (8, 107, 1, 1, '2026-04-15', 3500);

INSERT INTO credits (id, customer_id, issued_on, reason, amount_cents) VALUES
    (201, 2, '2026-03-08', 'billing_error', 1500),
    (202, 1, '2026-03-18', 'promo', 1000),
    (203, 3, '2026-04-02', 'adjustment', 700),
    (204, 4, '2026-03-11', 'refund', 1000),
    (205, 2, '2026-03-25', 'adjustment', 800),
    (206, 4, '2026-04-10', 'promo', 500);

INSERT INTO credit_applications (id, credit_id, invoice_id, customer_id, applied_on, amount_cents) VALUES
    (1, 201, 6, 2, '2026-03-16', 1500),
    (2, 202, 2, 1, '2026-03-28', 1000),
    (3, 203, 8, 3, '2026-04-05', 700),
    (4, 204, 5, 4, '2026-03-31', 1000),
    (5, 205, 3, 2, '2026-03-29', 800);

-- A fully paid April invoice must never enter the March ranking or Q6.
INSERT INTO invoices VALUES (9,3,3,'2026-04-01','2026-05-01','issued');
INSERT INTO invoice_lines VALUES (12,9,'April annual fee',12000);
INSERT INTO payments VALUES (108,3,3,'2026-04-30',12000,'succeeded');
INSERT INTO payment_allocations VALUES (9,108,9,3,'2026-04-30',12000);
