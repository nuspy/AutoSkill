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

        # Parents before children, so every foreign key already points at a row that exists. The
        # source is copied inside one target transaction: it all lands, or nothing does.
        tables = [t for t in Base.metadata.sorted_tables if t.name != ALEMBIC]
        async with src.connect() as sc, tgt.begin() as tc:
            for tbl in reversed(tables):  # children first for the delete, so no FK blocks it
                await tc.execute(delete(tbl))
            total = 0
            for tbl in tables:
                rows = [dict(r) for r in (await sc.execute(select(tbl))).mappings()]
                if rows:
                    for i in range(0, len(rows), batch):
                        await tc.execute(insert(tbl), rows[i : i + batch])
                total += len(rows)
                print(f"  {tbl.name}: {len(rows)}")
            print(f"copied {total} rows across {len(tables)} tables")
        # Postgres sequences (SERIAL/identity) are not advanced by an explicit-id insert; AutoSkill
        # uses string ids everywhere, so there are none to reset. If that ever changes, reset them here.
    finally:
        await src.dispose()
        await tgt.dispose()


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
