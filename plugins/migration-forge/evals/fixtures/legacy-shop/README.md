# legacy-shop (fixture)
Deliberately dated Express 4.16 + jQuery 1.12 + MySQL 5.7 app with planted issues for migration-forge evals:
string-built SQL (server.js), DOM XSS (public/app.js), hardcoded placeholder DB password (config.js),
TINYINT(1) holding 2 and a zero date in seed data, ENUM + ON UPDATE CURRENT_TIMESTAMP columns,
business rules BR-1..BR-3 in server.js comments.
