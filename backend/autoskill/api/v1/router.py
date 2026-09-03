from fastapi import APIRouter

from autoskill.api.v1 import (
    admin,
    api_keys,
    auth,
    devices,
    events,
    health,
    notifications,
    projects,
    users,
)

api_router = APIRouter(prefix="/api/v1")
for module in (health, auth, users, projects, api_keys, devices, notifications, events, admin):
    api_router.include_router(module.router)
