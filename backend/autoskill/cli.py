"""Server-side management CLI (`autoskill-server`)."""

from __future__ import annotations

import asyncio

import typer
import uvicorn
from sqlalchemy import select

from autoskill.config import get_settings

app = typer.Typer(help="AutoSkill server management")


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    uvicorn.run("autoskill.main:app", host=host, port=port, reload=reload)


@app.command()
def migrate() -> None:
    """Apply database migrations (alembic upgrade head)."""
    from alembic.config import Config

    from alembic import command

    command.upgrade(Config("alembic.ini"), "head")


@app.command()
def create_admin(email: str, password: str, name: str = "Admin") -> None:
    from autoskill.core.security import hash_password
    from autoskill.db.session import get_session_factory
    from autoskill.models.user import User, UserRole

    async def _run() -> None:
        async with get_session_factory()() as session:
            res = await session.execute(select(User).where(User.email == email.lower()))
            user = res.scalar_one_or_none()
            if user is None:
                user = User(email=email.lower(), password_hash=hash_password(password),
                            display_name=name, role=UserRole.admin)
                session.add(user)
            else:
                user.role = UserRole.admin
                user.password_hash = hash_password(password)
            await session.commit()
            typer.echo(f"admin ready: {email}")

    asyncio.run(_run())


@app.command()
def info() -> None:
    s = get_settings()
    typer.echo(f"env={s.env} db={s.database_url} jobs={s.jobs} events={s.events} data={s.data_dir}")


if __name__ == "__main__":
    app()
