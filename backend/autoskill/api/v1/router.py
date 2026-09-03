from fastapi import APIRouter

from autoskill.api.v1 import (
    admin,
    api_keys,
    auth,
    data_sources,
    devices,
    events,
    health,
    interview,
    memory,
    notifications,
    projects,
    providers,
    skills,
    users,
)

api_router = APIRouter(prefix="/api/v1")
for module in (
    health,
    auth,
    users,
    projects,
    api_keys,
    devices,
    notifications,
    events,
    admin,
    providers,
    data_sources,
    skills,
    interview,
    memory,
):
    api_router.include_router(module.router)
