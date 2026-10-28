INSERT INTO customers (id, email, name, is_active, created_at) VALUES
 (42, 'ana@example.test', 'Ana', 1, '2017-03-01 10:00:00'),
 (43, 'bo@example.test', 'Bo', 2, '0000-00-00 00:00:00');
INSERT INTO orders (id, customer_id, status, total, created_at) VALUES
 (1, 42, 'NEW', 120.50, '2017-03-02 09:15:00'),
 (2, 42, 'PAID', 99.99, '2017-03-05 18:40:00'),
 (3, 43, 'CANCELLED', 15.00, '2017-03-26 02:30:00');
