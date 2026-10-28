# SQL Server notes

## Upgrade paths
- **In-place or side-by-side** (backup/restore, or a log-shipping cutover).
  - Run Data Migration Assistant (DMA) or Azure Migrate first, to find breaking changes and deprecated features.
  - After restoring, raise the database **compatibility level** in a separate, tested step. Keep Query Store on to catch plan regressions (enable it before raising the level).
- **To Azure SQL / Managed Instance:** use Azure Database Migration Service (online mode for minimal downtime).
- **Online index ops** (`ONLINE = ON`) need Enterprise edition or Azure.

## Gotchas when migrating FROM SQL Server
- **T-SQL procedural code:** temp tables, `@@IDENTITY` vs `SCOPE_IDENTITY()`, `TRY…CATCH`, cursors, `MERGE`, and `OUTPUT`. Each needs a BR id plus a test or eval case. Prefer moving the logic into application code.
- `NVARCHAR` stores UTF-16, so lengths are characters. Map to `VARCHAR` (Postgres, UTF-8) carefully, and check the max lengths.
- `DATETIME` has about 3 ms precision, rounded to .000/.003/.007. `DATETIME2` and Postgres keep microseconds. Use normalized comparison (db_verify does), and decide the rounding.
- `MONEY` has 4-decimal fixed rounding. Map it to `NUMERIC(19,4)`.
- `UNIQUEIDENTIFIER` sort order differs from Postgres `uuid`. Don't rely on `ORDER BY` a GUID.
- Default collation `SQL_Latin1_General_CP1_CI_AS` is case-insensitive and accent-sensitive. Port it with `citext` or `ILIKE`, or a case-insensitive collation (PG ≥12 nondeterministic ICU collations), and test it.
- `IDENTITY` gaps and reseeds. Linked servers and cross-database queries need a replacement design.
- `bit` → `boolean`. `TOP n` → `LIMIT n`. String concatenation with `+` vs `||`, and NULL handling (`CONCAT_NULL_YIELDS_NULL`).

## Driver notes
- **pyodbc** needs "ODBC Driver 18 for SQL Server", which enforces encryption by default. db_verify sets `TrustServerCertificate=yes` for local and test use only.
- **JDBC:** `mssql-jdbc` has `encrypt=true` as the default since v10.
