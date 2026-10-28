---
description: Reference method for SQL database migrations in legacy modernization - strategy selection (in-place upgrade, expand/contract, dual-write/CDC, big-bang), zero-downtime schema change rules, cross-engine type mapping, migration tooling (Flyway, Liquibase, Alembic, Prisma, EF Core) and verification with db_verify.py. Use when planning or writing any database migration, schema change or data copy.
user-invocable: false
---

> This is the optional DB track. In a migration workspace, apply it only when `db_migration` is true in `forge/state.json`. When it is off, the existing database stays unchanged.

# SQL database migration method

## 1. Choose the strategy (write the reason in `forge/db/strategy.md`)
| Situation | Strategy |
|-----------|----------|
| Same engine, newer version, schema unchanged | **In-place upgrade.** Use the engine's upgrade path (pg_upgrade / logical replication, MySQL in-place or logical dump, SQL Server backup/restore at the new compatibility level). Then run the app test suite. |
| Schema changes while the app stays live | **Expand → migrate → contract.** Add the new structures, backfill them, dual-read or dual-write in the app, switch reads, then drop the old ones in a later release. |
| Engine change, downtime budget ≥ bulk copy + verify time | **Big-bang copy.** Freeze writes, copy, verify, switch the connection, and keep the legacy DB read-only for N days. |
| Engine change, small downtime budget | **CDC / dual-write.** Bulk copy, stream changes (Debezium, AWS DMS, pglogical, Azure DMS), verify while the lag is near zero, then do a short freeze and switch. |

## 2. Zero-downtime rules (any engine)
- Every change is backward compatible with the currently deployed app version. Never rename or drop in the same release as the code change.
- New NOT NULL columns: add them as nullable, backfill in batches, then add the constraint. On Postgres, use `CHECK … NOT VALID` followed by `VALIDATE`.
- Build indexes online. Postgres: `CREATE INDEX CONCURRENTLY`, which can't run inside a transaction. MySQL: `ALGORITHM=INPLACE, LOCK=NONE`. SQL Server: `ONLINE = ON` (Enterprise or Azure).
- Backfills run in batches of 1k–10k rows with a pause, keyed by PK range. They must be resumable and idempotent.
- Set lock and statement timeouts for DDL. Postgres example: `SET lock_timeout = '5s'`.
- Each migration does one logical change, is versioned, and is never edited after it has been applied.

## 3. Tooling. Use the one in `forge/decisions/target-stack.json`.
| Tool | Forward | Rollback |
|------|---------|----------|
| Flyway | `V<ver>__desc.sql` | `U<ver>__desc.sql` (undo needs Teams/Enterprise; otherwise keep a down script per version and run it through `R`/a manual step, documented) |
| Liquibase | changeSet | a `rollback` block in every changeSet; `liquibase rollback-count 1` |
| Alembic | `upgrade()` | `downgrade()`; `alembic downgrade -1` |
| Prisma Migrate | `migrate deploy` | no native down: write `down.sql` next to each migration and test it with db_verify reversibility |
| EF Core | `Up()` | `Down()`; `dotnet ef database update <prev>` |

## 4. Cross-engine type mapping
Highest-risk pairs. The per-engine references have more detail.
| MySQL | SQL Server | PostgreSQL | Watch out |
|-------|-----------|------------|-----------|
| TINYINT(1) | BIT | BOOLEAN | the app may store 2..255 in TINYINT(1). Check the data first |
| DATETIME | DATETIME2 | TIMESTAMP (no tz) | time zone semantics. Decide UTC and document it |
| TIMESTAMP | DATETIMEOFFSET | TIMESTAMPTZ | MySQL converts to the session tz |
| DECIMAL(p,s) | DECIMAL / MONEY | NUMERIC(p,s) | MONEY rounding. Never map money to FLOAT |
| ENUM('a','b') | CHECK constraint | native ENUM type or CHECK | ordering semantics |
| VARCHAR(n) utf8mb4 | NVARCHAR(n) | VARCHAR(n) / TEXT | length is bytes vs chars; collation and case sensitivity |
| AUTO_INCREMENT | IDENTITY | GENERATED … AS IDENTITY | re-seed after the copy: `setval(…, max(id))` |
| JSON | NVARCHAR(MAX) + ISJSON | JSONB | key order and duplicate keys |
| BLOB | VARBINARY(MAX) | BYTEA | size |
| `''` vs NULL | | | Oracle treats `''` as NULL |

Case sensitivity: MySQL and SQL Server collations are usually case-insensitive, and Postgres is case-sensitive. Cover every `WHERE` on text that users type with a test or a Jenkins eval case.

## 5. Procedural code
Stored procedures, triggers, and functions either move into application code, which is preferred for testability, or get ported (T-SQL / PL/SQL → PL/pgSQL). Each one needs a business-rule id and an eval case. Tools: ora2pg (Oracle), AWS SCT, and the SQL Server Migration Assistant for the assessment.

## 6. Evidence (`forge/db/verify.json`, attached to the DB tickets)
1. `db_verify.py reversibility`: run on a disposable container DB. It proves down restores the schema and up is repeatable.
2. `db_verify.py compare --map forge/db/map.json`: per-table row count plus an order-independent checksum over normalized values. The target is 100%.
3. squawk for Postgres migrations.
4. Result-equality checks for reports and aggregates. Ask the Jenkins pipeline owners to add them to the evals.

Secrets: connection URLs live only in environment variables (`FORGE_SOURCE_DB_URL`, `FORGE_TARGET_DB_URL`, `FORGE_SCRATCH_DB_URL`).

## References
Load only the engines involved: `references/postgres.md`, `references/mysql.md`, `references/mssql.md`.
