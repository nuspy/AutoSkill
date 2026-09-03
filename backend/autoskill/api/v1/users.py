from fastapi import APIRouter

from autoskill.api.v1.deps import CurrentUser, SessionDep
from autoskill.core.errors import Unauthorized
from autoskill.core.security import hash_password, verify_password
from autoskill.schemas.common import OkResponse
from autoskill.schemas.user import PasswordChange, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/me", response_model=UserOut)
async def update_me(body: UserUpdate, session: SessionDep, user: CurrentUser):
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.locale is not None:
        user.locale = body.locale
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/me/password", response_model=OkResponse)
async def change_password(body: PasswordChange, session: SessionDep, user: CurrentUser):
    if not verify_password(body.current_password, user.password_hash):
        raise Unauthorized("invalid_credentials")
    user.password_hash = hash_password(body.new_password)
    await session.commit()
    return OkResponse()
