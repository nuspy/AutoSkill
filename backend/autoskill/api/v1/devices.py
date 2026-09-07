from fastapi import APIRouter
from sqlalchemy import select

from autoskill.api.v1.deps import AnyAuthUser, ApiKeyDep, CurrentUser, SessionDep
from autoskill.core.errors import NotFound
from autoskill.db.base import utcnow
from autoskill.models.api_key import ApiKey
from autoskill.models.device import Device
from autoskill.schemas.bundle import CompanionEntry
from autoskill.schemas.common import OkResponse
from autoskill.schemas.device import DeviceHeartbeat, DeviceOut
from autoskill.services.distribution import bundle as bundles

router = APIRouter(tags=["devices"])


@router.get("/devices/companion", response_model=CompanionEntry)
async def companion() -> CompanionEntry:
    """What to install to connect a machine, resolved to the wheel this server publishes.

    `autoskill-local` is not on PyPI - that name is taken by an unrelated package - so the
    command has to name a versioned URL under /dl, which only the server can build. Public,
    like the wheel it points at: the page that shows the command is what a person reads
    before having anything to authenticate with.
    """
    return bundles.companion_entry()


@router.get("/me/devices", response_model=list[DeviceOut])
async def list_devices(session: SessionDep, user: AnyAuthUser):
    res = await session.execute(select(Device).where(Device.user_id == user.id).order_by(Device.created_at.desc()))
    return res.scalars().all()


@router.delete("/me/devices/{device_id}", response_model=OkResponse)
async def remove_device(device_id: str, session: SessionDep, user: CurrentUser):
    device = await session.get(Device, device_id)
    if device is None or device.user_id != user.id:
        raise NotFound("device_not_found")
    res = await session.execute(select(ApiKey).where(ApiKey.device_id == device.id))
    for key in res.scalars():
        key.revoked_at = utcnow()
    await session.delete(device)
    await session.commit()
    return OkResponse()


@router.post("/devices/heartbeat", response_model=DeviceOut)
async def heartbeat(body: DeviceHeartbeat, session: SessionDep, key: ApiKeyDep):
    """Called by the CLI to refresh device metadata; authenticated with the device key."""
    if key.device_id is None:
        raise NotFound("device_not_found")
    device = await session.get(Device, key.device_id)
    if device is None:
        raise NotFound("device_not_found")
    if body.agent_targets is not None:
        device.agent_targets = body.agent_targets
    if body.cli_version:
        device.cli_version = body.cli_version
    if body.os:
        device.os = body.os
    device.last_seen_at = utcnow()
    await session.commit()
    await session.refresh(device)
    return device
