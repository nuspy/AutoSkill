"""Copy an AutoSkill SQLite database into a PostgreSQL one, table by table.

Why this exists: on SQLite a single writer holds the database for the length of its transaction, and
AutoSkill's interview and trial jobs keep a write transaction open across an LLM call that can last
minutes — so an ordinary login, whose only job is to write an audit row, times out with "database is
locked". PostgreSQL has none of that. Switching is only useful if the data comes along, and that is
what this does: it moves every row, in foreign-key-safe order, from the SQLite file into a Postgres
database that already has the schema.

Run the schema first (`alembic upgrade head` against the target), then this. The installer does both
for you when you choose PostgreSQL and an SQLite database is already there; run it by hand with:

    AUTOSKILL_DATABASE_URL=postgresql+asyncpg://autoskill:PW@localhost:5432/autoskill \
        alembic -c backend/alembic.ini upgrade head
    python deploy/migrate_sqlite_to_postgres.py \
        --source sqlite+aiosqlite:///backend/autoskill.db \
        --target postgresql+asyncpg://autoskill:PW@localhost:5432/autoskill

It is safe to re-run: each table is emptied on the target before its rows are copied, so a second run
replaces rather than duplicates. The target must already be migrated to the same revision; the copy
refuses to run if the two schemas' migration revisions differ, because copying into a mismatched
schema is how silent data loss happens.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import autoskill.models  # noqa: F401 — importing registers every model on the shared metadata
from autoskill.db.base import Base
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine

ALEMBIC = "alembic_version"


async def _revision(conn) -> str | None:
    try:
        return (await conn.execute(text(f"SELECT version_num FROM {ALEMBIC}"))).scalar_one_or_none()
    except Exception:  # noqa: BLE001 — a table that is not there answers the question: no revision
        return None


async def _foreign_keys(tc) -> list[tuple[str, str, str]]:
    """Every foreign key on the target as (table, constraint name, definition)."""
    rows = await tc.execute(
        text(
            "SELECT conrelid::regclass::text AS tbl, conname, pg_get_constraintdef(oid) AS def "
            "FROM pg_constraint WHERE contype = 'f'"
        )
    )
    return [(t.split(".")[-1].strip('"'), n, d) for t, n, d in rows]


async def migrate(source_url: str, target_url: str, *, batch: int = 500) -> None:
    src = create_async_engine(source_url)
    tgt = create_async_engine(target_url)
    try:
        async with src.connect() as sc, tgt.connect() as tc:
            src_rev, tgt_rev = await _revision(sc), await _revision(tc)
            if tgt_rev is None:
                raise SystemExit(
                    "the target has no schema — run `alembic upgrade head` against it first "
                    "(the installer does this for you)."
                )
            if src_rev != tgt_rev:
                raise SystemExit(
                    f"schema mismatch: source is at revision {src_rev!r}, target at {tgt_rev!r}. "
                    "Migrate both to the same revision before copying."
                )

        by_name = {t.name: t for t in Base.metadata.sorted_tables if t.name != ALEMBIC}
        # One transaction: drop the foreign keys, copy every row in any order, then put the keys back.
        # SQLite does not enforce foreign keys unless asked, so a real database often carries dangling
        # references (an api_key whose device row was deleted); Postgres does enforce them and would
        # reject the copy row by row. Dropping the constraints for the copy sidesteps the ordering
        # problem entirely, and re-adding them NOT VALID keeps every existing row while still enforcing
        # every future write — with the dangling ones named in the output so they are not a silent loss.
        async with src.connect() as sc, tgt.begin() as tc:
            fks = await _foreign_keys(tc)
            for tbl, name, _ in fks:
                await tc.execute(text(f'ALTER TABLE "{tbl}" DROP CONSTRAINT "{name}"'))
            total = 0
            for name, tbl in by_name.items():
                await tc.execute(delete(tbl))
                rows = [dict(r) for r in (await sc.execute(select(tbl))).mappings()]
                for i in range(0, len(rows), batch):
                    await tc.execute(insert(tbl), rows[i : i + batch])
                total += len(rows)
                print(f"  {name}: {len(rows)}")
            for tbl, name, definition in fks:
                await tc.execute(text(f'ALTER TABLE "{tbl}" ADD CONSTRAINT "{name}" {definition} NOT VALID'))
            print(f"copied {total} rows across {len(by_name)} tables; {len(fks)} foreign keys restored")
            # Report references that point at nothing — data SQLite let through, now visible.
            dangling = 0
            for tbl, name, definition in fks:
                bad = (await tc.execute(text(f'SELECT count(*) FROM "{tbl}" t WHERE NOT ({_fk_holds(definition)})'))).scalar_one()
                if bad:
                    dangling += bad
                    print(f"  ! {tbl}.{name}: {bad} row(s) reference a missing parent (kept; constraint NOT VALID)")
            if dangling:
                print(f"{dangling} dangling reference(s) carried over — clean them and VALIDATE the constraints if wanted")
        # AutoSkill uses string ids throughout, so there are no sequences to reset after an id insert.
    finally:
        await src.dispose()
        await tgt.dispose()


def _fk_holds(definition: str) -> str:
    """A boolean SQL expression that is true when a row's foreign key is satisfied, from the FK def.

    `pg_get_constraintdef` reads `FOREIGN KEY (col[, ...]) REFERENCES parent(pcol[, ...])`. Turned into
    `(col IS NULL OR EXISTS (SELECT 1 FROM parent WHERE parent.pcol = t.col))` it counts the rows whose
    reference points at nothing — a NULL reference is always fine.
    """
    import re

    m = re.search(r"FOREIGN KEY \(([^)]+)\) REFERENCES ([^\s(]+)\s*\(([^)]+)\)", definition)
    if not m:
        return "TRUE"
    cols = [c.strip().strip('"') for c in m.group(1).split(",")]
    parent = m.group(2)
    pcols = [c.strip().strip('"') for c in m.group(3).split(",")]
    null_ok = " OR ".join(f't."{c}" IS NULL' for c in cols)
    joins = " AND ".join(f'p."{pc}" = t."{c}"' for c, pc in zip(cols, pcols, strict=False))
    return f'({null_ok} OR EXISTS (SELECT 1 FROM {parent} p WHERE {joins}))'


def main() -> None:
    ap = argparse.ArgumentParser(description="Copy an AutoSkill SQLite database into PostgreSQL.")
    ap.add_argument("--source", required=True, help="source SQLite URL (sqlite+aiosqlite:///path)")
    ap.add_argument("--target", required=True, help="target Postgres URL (postgresql+asyncpg://...)")
    args = ap.parse_args()
    if not args.source.startswith("sqlite"):
        sys.exit("--source must be a sqlite URL")
    if "postgresql" not in args.target:
        sys.exit("--target must be a postgresql URL")
    asyncio.run(migrate(args.source, args.target))


if __name__ == "__main__":
    main()
