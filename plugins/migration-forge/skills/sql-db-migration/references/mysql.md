# MySQL / MariaDB notes

## Upgrade paths
- **Run the MySQL Shell upgrade checker** before any major upgrade: `util.checkForServerUpgrade()`. It reports removed features, reserved words, and auth plugin changes.
- **5.7 → 8.0:**
  - Default auth becomes `caching_sha2_password`, so old drivers fail. Update the drivers.
  - Many new reserved words. Quote identifiers such as `rank` and `groups`.
  - The default charset becomes `utf8mb4` with collation `utf8mb4_0900_ai_ci`. Joins against `utf8` columns can hit collation mismatch errors.
  - The query cache is removed.
- **8.0 → 8.4 LTS:** `mysql_native_password` is disabled by default. Some deprecated variables and syntax are removed.
- **MariaDB** has diverged (JSON is LONGTEXT, a different optimizer and system-versioned tables). Treat it as its own engine.
- **Online schema change on large tables:** `gh-ost` or `pt-online-schema-change`. Use them when `ALGORITHM=INSTANT/INPLACE` isn't possible.

## Gotchas when migrating FROM MySQL
- **`sql_mode`:** legacy apps often relied on a lax mode (no `STRICT_TRANS_TABLES`), which silently truncates data and inserts zero dates.
  - Before copying, scan for `0000-00-00` dates, over-length strings, and invalid enum values.
  - Decide a mapping for them, such as NULL or a sentinel, and record it in strategy.md.
- `TINYINT(1)` isn't always boolean. Check with `SELECT DISTINCT col`.
- `utf8` (3-byte) vs `utf8mb4`: emoji and 4-byte characters may already be mangled in the source. Compare checksums on a sample before trusting the data.
- Case-insensitive default collations: unique keys may treat 'A' and 'a' as duplicates. On a case-sensitive target, both might be inserted.
- `GROUP BY` with non-aggregated columns (when ONLY_FULL_GROUP_BY was off) gives nondeterministic results. Port these to explicit aggregates, and cover them with order-independent result checks (tests or Jenkins evals).
- `ON UPDATE CURRENT_TIMESTAMP` columns: emulate them with a trigger or in the app. Exclude them from db_verify only if they get rewritten during the copy, and give a reason.
- `LIMIT x,y` becomes `OFFSET/FETCH` or `LIMIT … OFFSET`. Backtick identifiers become standard double quotes.
