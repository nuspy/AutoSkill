from fastapi import APIRouter
from sqlalchemy import text

from autoskill import __version__
from autoskill.api.v1.deps import SessionDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: SessionDep) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}
