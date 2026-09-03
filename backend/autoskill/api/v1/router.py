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
    library,
    memory,
    notifications,
    projects,
    providers,
    runs,
    skills,
    telemetry,
    trials,
    users,
    versions,
)

MODULES = (
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
    versions,
    library,
    trials,
    telemetry,
    runs,
)

api_router = APIRouter(prefix="/api/v1")
for module in MODULES:
    api_router.include_router(module.router)
