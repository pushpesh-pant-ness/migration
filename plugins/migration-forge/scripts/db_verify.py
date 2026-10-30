#!/usr/bin/env python3
"""Deterministic database migration evidence -> forge/db/verify.json

Connection URLs come from ENVIRONMENT VARIABLES only (never written to disk):
  postgresql://user:pw@host:5432/db   mysql://user:pw@host:3306/db
  mssql://user:pw@host:1433/db        sqlite:///path/to.db
Drivers (install what you need): psycopg or psycopg2, pymysql or mysql-connector-python, pyodbc or pymssql.

  db_verify.py compare --source-env FORGE_SOURCE_DB_URL --target-env FORGE_TARGET_DB_URL [--map map.json]
      Per table: row count + order-independent content checksum over the common, mapped columns.
      Values are normalised across engines (numbers, booleans, timestamps, bytes, JSON, CHAR padding).
      A source column with no target column (not mapped, not excluded) fails its table: that data would be lost.
      Target tables with no source table are listed (extra_target_tables) but don't fail.
      map.json: {"tables": {"old": "new"}, "columns": {"old_table": {"old_col": "new_col"}},
                 "exclude_columns": {"old_table": ["col"]}, "exclude_tables": ["audit_log"]}
  db_verify.py reversibility --target-env FORGE_SCRATCH_DB_URL --up "flyway migrate" --down "flyway undo" [--allow-remote]
      On a DISPOSABLE database: schema(before) -> up -> down == before -> up again == first up. The schema snapshot
      covers columns, indexes, constraints (incl. foreign keys), views, triggers and sequences.
      Refused unless the database is local (localhost, 127.0.0.1, ::1, host.docker.internal, a sqlite file) and its
      host and name don't mention prod; --allow-remote overrides that, and the guard asks the human first.
  db_verify.py snapshot --env FORGE_TARGET_DB_URL         # print schema snapshot JSON
"""
import argparse
import datetime as dt
import decimal
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import uuid

from forgelib import forge, now, read_json, write_json

HISTORY_TABLES = {"flyway_schema_history", "databasechangelog", "databasechangeloglock", "alembic_version",
                  "_prisma_migrations", "__efmigrationshistory", "schema_migrations", "knex_migrations",
                  "knex_migrations_lock", "sequelizemeta", "doctrine_migration_versions", "migrations"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", ""}

# Schema objects beyond columns, per engine. The first column of each query is the table the object belongs to (or the
# object itself), so objects of the migration tool's history tables can be left out like the tables are.
OBJECT_SQL = {
    "pg": {
        "indexes": "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()",
        "constraints": "SELECT conrelid::regclass::text, conname, contype::text, pg_get_constraintdef(oid) "
                       "FROM pg_constraint WHERE connamespace = current_schema()::regnamespace",
        "views": "SELECT table_name, view_definition FROM information_schema.views WHERE table_schema = current_schema()",
        "triggers": "SELECT event_object_table, trigger_name, event_manipulation, action_timing "
                    "FROM information_schema.triggers WHERE trigger_schema = current_schema()",
        "sequences": "SELECT sequence_name, data_type FROM information_schema.sequences "
                     "WHERE sequence_schema = current_schema()",
        "routines": "SELECT routine_name, routine_type FROM information_schema.routines "
                    "WHERE routine_schema = current_schema()",
    },
    "my": {
        "indexes": "SELECT table_name, index_name, non_unique, GROUP_CONCAT(column_name ORDER BY seq_in_index) "
                   "FROM information_schema.statistics WHERE table_schema = DATABASE() "
                   "GROUP BY table_name, index_name, non_unique",
        "constraints": "SELECT tc.table_name, tc.constraint_name, tc.constraint_type, "
                       "GROUP_CONCAT(CONCAT(k.column_name, '>', COALESCE(k.referenced_table_name, ''), '.', "
                       "COALESCE(k.referenced_column_name, '')) ORDER BY k.ordinal_position) "
                       "FROM information_schema.table_constraints tc LEFT JOIN information_schema.key_column_usage k "
                       "ON k.constraint_schema = tc.constraint_schema AND k.table_name = tc.table_name "
                       "AND k.constraint_name = tc.constraint_name WHERE tc.table_schema = DATABASE() "
                       "GROUP BY tc.table_name, tc.constraint_name, tc.constraint_type",
        "views": "SELECT table_name, view_definition FROM information_schema.views WHERE table_schema = DATABASE()",
        "triggers": "SELECT event_object_table, trigger_name, event_manipulation, action_timing "
                    "FROM information_schema.triggers WHERE trigger_schema = DATABASE()",
        "routines": "SELECT routine_name, routine_type FROM information_schema.routines WHERE routine_schema = DATABASE()",
    },
    "ms": {
        "indexes": "SELECT t.name, i.name, i.type_desc, i.is_unique, STUFF((SELECT ',' + c.name FROM sys.index_columns ic "
                   "JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
                   "WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id ORDER BY ic.key_ordinal "
                   "FOR XML PATH('')), 1, 1, '') FROM sys.indexes i JOIN sys.tables t ON t.object_id = i.object_id "
                   "WHERE t.schema_id = SCHEMA_ID() AND i.name IS NOT NULL",
        "constraints": "SELECT table_name, constraint_name, constraint_type FROM information_schema.table_constraints "
                       "WHERE table_schema = SCHEMA_NAME()",
        "foreign_keys": "SELECT OBJECT_NAME(f.parent_object_id), f.name, OBJECT_NAME(f.referenced_object_id), "
                        "f.delete_referential_action_desc FROM sys.foreign_keys f WHERE f.schema_id = SCHEMA_ID()",
        "views": "SELECT table_name, view_definition FROM information_schema.views WHERE table_schema = SCHEMA_NAME()",
        "triggers": "SELECT t.name, tr.name, tr.is_disabled FROM sys.triggers tr JOIN sys.tables t "
                    "ON t.object_id = tr.parent_id WHERE t.schema_id = SCHEMA_ID()",
        "sequences": "SELECT name, CAST(start_value AS VARCHAR(40)) FROM sys.sequences WHERE schema_id = SCHEMA_ID()",
        "routines": "SELECT routine_name, routine_type FROM information_schema.routines "
                    "WHERE routine_schema = SCHEMA_NAME()",
    },
    "lite": {
        "objects": "SELECT tbl_name, type, name, COALESCE(sql, '') FROM sqlite_master "
                   "WHERE type IN ('index', 'view', 'trigger') AND name NOT LIKE 'sqlite_%'",
    },
}


def history_object(name):
    n = str(name).split(".")[-1].strip('"`[]').lower()
    return any(n == h or n.startswith(h + "_") for h in HISTORY_TABLES)


def disposable_problem(url):
    """Why the database at `url` may not be a disposable one, or None."""
    u = urllib.parse.urlparse(url)
    host = "" if u.scheme.startswith("sqlite") else (u.hostname or "").lower()
    if re.search(r"(^|[^a-z])prod(uction)?([^a-z]|$)", f"{host} {u.path.lower()}"):
        return f"'{host or u.path}' looks like a production database"
    if host not in LOCAL_HOSTS and not host.endswith(".localhost"):
        return f"host '{host}' is not local (use a throwaway container on localhost)"
    return None


class DB:
    def __init__(self, url):
        u = urllib.parse.urlparse(url)
        self.kind = {"postgres": "pg", "postgresql": "pg", "mysql": "my", "mariadb": "my",
                     "mssql": "ms", "sqlserver": "ms", "sqlite": "lite"}.get(u.scheme.split("+")[0])
        if not self.kind:
            sys.exit(f"unsupported scheme {u.scheme}")
        user, pw = urllib.parse.unquote(u.username or ""), urllib.parse.unquote(u.password or "")
        name = u.path.lstrip("/")
        if self.kind == "pg":
            try:
                import psycopg as drv
            except ImportError:
                import psycopg2 as drv
            self.con = drv.connect(url.replace("postgres://", "postgresql://", 1))
            self.q = '"'
        elif self.kind == "my":
            try:
                import pymysql
                self.con = pymysql.connect(host=u.hostname, port=u.port or 3306, user=user, password=pw, database=name)
            except ImportError:
                import mysql.connector
                self.con = mysql.connector.connect(host=u.hostname, port=u.port or 3306, user=user, password=pw, database=name)
            self.q = "`"
        elif self.kind == "ms":
            try:
                import pyodbc
                drvname = urllib.parse.parse_qs(u.query).get("driver", ["ODBC Driver 18 for SQL Server"])[0]
                self.con = pyodbc.connect(f"DRIVER={{{drvname}}};SERVER={u.hostname},{u.port or 1433};DATABASE={name};"
                                          f"UID={user};PWD={pw};TrustServerCertificate=yes")
            except ImportError:
                import pymssql
                self.con = pymssql.connect(server=u.hostname, port=u.port or 1433, user=user, password=pw, database=name)
            self.q = '"'
        else:
            import sqlite3
            path = u.path[1:] if u.path.startswith("//") or re.match(r"^/[A-Za-z]:", u.path) else u.path  # sqlite:///C:/x.db
            self.con = sqlite3.connect(urllib.parse.unquote(path))
            self.q = '"'

    def all(self, sql, params=()):
        c = self.con.cursor()
        c.execute(sql, params) if params else c.execute(sql)
        return c.fetchall()

    def ident(self, s):
        return f"{self.q}{s}{self.q}"

    def schema_filter(self):
        return {"pg": "table_schema = current_schema()", "my": "table_schema = DATABASE()",
                "ms": "table_schema = SCHEMA_NAME()"}[self.kind]

    def tables(self):
        if self.kind == "lite":
            rows = self.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        else:
            rows = self.all(f"SELECT table_name FROM information_schema.tables WHERE {self.schema_filter()} "
                            "AND table_type = 'BASE TABLE'")
        return sorted(r[0] for r in rows)

    def columns(self, table):
        if self.kind == "lite":
            return [(r[1], r[2], not r[3]) for r in self.all(f"PRAGMA table_info({self.ident(table)})")]
        ph = "%s" if self.kind in ("pg", "my") else "?"
        if self.kind == "ms" and "pymssql" in type(self.con).__module__:
            ph = "%s"
        rows = self.all(f"SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE "
                        f"{self.schema_filter()} AND table_name = {ph} ORDER BY ordinal_position", (table,))
        return [(r[0], r[1], r[2] == "YES") for r in rows]

    def objects(self):
        """Indexes, constraints, views, triggers, sequences and routines: {section: sorted rows}."""
        out = {}
        for section, sql in OBJECT_SQL[self.kind].items():
            try:
                rows = [[None if v is None else str(v) for v in r] for r in self.all(sql)]
            except Exception as e:  # a missing privilege or an old server version: record it, don't crash
                try:
                    self.con.rollback()
                except Exception:
                    pass
                rows = [["error", str(e)[:200]]]
            out[section] = sorted((r for r in rows if not history_object(r[0])), key=lambda r: [x or "" for x in r])
        if self.kind == "lite":
            out["foreign_keys"] = sorted([t, *[str(v) for v in r[2:5]]] for t in self.tables()
                                         if not history_object(t)
                                         for r in self.all(f"PRAGMA foreign_key_list({self.ident(t)})"))
        return out

    def stream(self, table, cols):
        c = self.con.cursor()
        c.execute(f"SELECT {', '.join(self.ident(x) for x in cols)} FROM {self.ident(table)}")
        while True:
            rows = c.fetchmany(5000)
            if not rows:
                return
            yield from rows


def norm(v, rstrip=True):
    if v is None:
        return "\x00"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (float, decimal.Decimal)):
        d = decimal.Decimal(repr(v)) if isinstance(v, float) else v
        if d.is_nan() or d.is_infinite():
            return str(d)
        s = format(d.normalize(), "f")
        return "0" if s in ("-0", "0") else s
    if isinstance(v, dt.datetime):
        if v.tzinfo:
            v = v.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return f"{v:%Y-%m-%d %H:%M:%S}.{v.microsecond:06d}"
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    if isinstance(v, uuid.UUID):
        return str(v).lower()
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, separators=(",", ":"))
    s = str(v)
    return s.rstrip(" ") if rstrip else s


def table_digest(db, table, cols):
    """Order-independent multiset digest: (count, sum of 64-bit row hashes mod 2^64)."""
    n, acc = 0, 0
    for row in db.stream(table, cols):
        h = hashlib.sha256("\x1f".join(norm(v) for v in row).encode("utf-8", "surrogatepass")).digest()
        acc = (acc + int.from_bytes(h[:8], "big")) % (1 << 64)
        n += 1
    return n, f"{acc:016x}"


def connect(env):
    url = os.environ.get(env)
    if not url:
        sys.exit(f"environment variable {env} is not set")
    return DB(url)


def cmd_compare(a):
    src, tgt = connect(a.source_env), connect(a.target_env)
    mp = read_json(a.map, {}) if a.map else {}
    tmap = {k.lower(): v.lower() for k, v in mp.get("tables", {}).items()}
    excl_t = {x.lower() for x in mp.get("exclude_tables", [])} | HISTORY_TABLES
    tgt_tables = {t.lower(): t for t in tgt.tables()}
    results, tot_rows, ok_rows = [], 0, 0
    for st in src.tables():
        if st.lower() in excl_t:
            continue
        tt = tgt_tables.get(tmap.get(st.lower(), st.lower()))
        r = {"table": st, "target_table": tt}
        if not tt:
            r.update(match=False, problem="missing in target")
            results.append(r)
            continue
        cmap = {k.lower(): v.lower() for k, v in mp.get("columns", {}).get(st, {}).items()}
        excl_c = {c.lower() for c in mp.get("exclude_columns", {}).get(st, [])}
        scols = [c for c, _, _ in src.columns(st) if c.lower() not in excl_c]
        tcols = {c.lower(): c for c, _, _ in tgt.columns(tt)}
        pairs = [(c, tcols[cmap.get(c.lower(), c.lower())]) for c in scols if cmap.get(c.lower(), c.lower()) in tcols]
        lost = r["source_only_columns"] = [c for c in scols if cmap.get(c.lower(), c.lower()) not in tcols]
        if not pairs:
            r.update(match=False, problem="no common columns")
            results.append(r)
            continue
        sn, sd = table_digest(src, st, [p[0] for p in pairs])
        tn, td = table_digest(tgt, tt, [p[1] for p in pairs])
        # A source column the target doesn't have is data that would be lost: map it, or exclude it with a reason.
        r.update(source_rows=sn, target_rows=tn, source_digest=sd, target_digest=td,
                 columns_compared=len(pairs), match=(sn == tn and sd == td and not lost))
        if lost:
            r["problem"] = f"source columns missing in target (map them or exclude them with a reason): {', '.join(lost)}"
        tot_rows += sn
        ok_rows += sn if r["match"] else 0
        results.append(r)
        print(f"{'OK ' if r['match'] else 'BAD'} {st:<32} rows {sn}->{tn}  cols {len(pairs)}"
              + (f"  missing columns: {', '.join(lost)}" if lost else ""), flush=True)
    used = {(r.get("target_table") or "").lower() for r in results}
    extra = sorted(t for k, t in tgt_tables.items() if k not in used and k not in HISTORY_TABLES)
    if extra:
        print(f"note: target tables with no source table: {', '.join(extra)}")
    pct = 100.0 if not tot_rows and all(r["match"] for r in results) else (100 * ok_rows / tot_rows if tot_rows else 0.0)
    out = forge() / "db" / "verify.json"
    v = read_json(out, {}) or {}
    v.update(compared_at=now(), tables=results, row_match_pct=round(pct, 4), extra_target_tables=extra,
             tables_total=len(results), tables_matched=sum(r["match"] for r in results))
    write_json(out, v)
    print(f"row match {pct:.4f}%  ({v['tables_matched']}/{v['tables_total']} tables)  -> {out}")
    sys.exit(0 if v["tables_matched"] == v["tables_total"] else 2)


def snapshot(db):
    return {"tables": {t: [list(c) for c in db.columns(t)] for t in db.tables() if t.lower() not in HISTORY_TABLES},
            "objects": db.objects()}


def snapshot_diff(a, b):
    """What differs between two snapshots, one line per table or object kind."""
    out = [f"table {t}" for t in sorted(set(a["tables"]) | set(b["tables"])) if a["tables"].get(t) != b["tables"].get(t)]
    for s in sorted(set(a["objects"]) | set(b["objects"])):
        x, y = a["objects"].get(s, []), b["objects"].get(s, [])
        if x != y:
            ch = ([f"-{'/'.join(map(str, r[:3]))}" for r in x if r not in y]
                  + [f"+{'/'.join(map(str, r[:3]))}" for r in y if r not in x])
            out.append(f"{s}: {'; '.join(ch[:10])}")
    return out


def cmd_snapshot(a):
    print(json.dumps(snapshot(connect(a.env)), indent=2, default=str))


def cmd_reversibility(a):
    def step(cmd):
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError(f"`{cmd}` failed rc={p.returncode}: {(p.stderr or p.stdout)[-2000:]}")

    url = os.environ.get(a.target_env) or sys.exit(f"environment variable {a.target_env} is not set")
    problem = disposable_problem(url)
    if problem and not a.allow_remote:
        sys.exit(f"REFUSED: reversibility runs up/down migrations, so it needs a DISPOSABLE database: {problem}. "
                 "If this database really is a throwaway one, the human confirms with --allow-remote.")
    rep = {"checked_at": now(), "up": a.up, "down": a.down, **({"remote_allowed": problem} if problem else {})}
    try:
        before = snapshot(connect(a.target_env))
        step(a.up)
        after_up = snapshot(connect(a.target_env))
        step(a.down)
        after_down = snapshot(connect(a.target_env))
        step(a.up)
        after_up2 = snapshot(connect(a.target_env))
        rep.update(down_restores_schema=after_down == before, up_is_repeatable=after_up2 == after_up,
                   schema_changed_by_up=after_up != before)
        if after_down != before:
            rep["down_diff"] = snapshot_diff(before, after_down)
        if after_up2 != after_up:
            rep["up_again_diff"] = snapshot_diff(after_up, after_up2)
        rep["reversible"] = rep["down_restores_schema"] and rep["up_is_repeatable"]
    except Exception as e:
        rep.update(reversible=False, error=str(e))
    out = forge() / "db" / "verify.json"
    v = read_json(out, {}) or {}
    v.update(reversible=rep["reversible"], reversibility=rep)
    write_json(out, v)
    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep["reversible"] else 2)


def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    c = s.add_parser("compare"); c.add_argument("--source-env", default="FORGE_SOURCE_DB_URL")
    c.add_argument("--target-env", default="FORGE_TARGET_DB_URL"); c.add_argument("--map")
    r = s.add_parser("reversibility"); r.add_argument("--target-env", default="FORGE_SCRATCH_DB_URL")
    r.add_argument("--up", required=True); r.add_argument("--down", required=True)
    r.add_argument("--allow-remote", action="store_true", help="the database is not local but is disposable (asks the human)")
    sn = s.add_parser("snapshot"); sn.add_argument("--env", default="FORGE_TARGET_DB_URL")
    a = p.parse_args()
    {"compare": cmd_compare, "reversibility": cmd_reversibility, "snapshot": cmd_snapshot}[a.cmd](a)


if __name__ == "__main__":
    main()
