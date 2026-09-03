"""ORM models. Import all modules so Alembic and create_all see every table."""

from autoskill.models.api_key import ApiKey
from autoskill.models.audit import AuditLog
from autoskill.models.blob import Blob
from autoskill.models.device import Device, DeviceAuthorization
from autoskill.models.job import Job
from autoskill.models.notification import Notification, NotificationPreference
from autoskill.models.project import Project, ProjectMember
from autoskill.models.system_setting import SystemSetting
from autoskill.models.user import RefreshToken, User

__all__ = [
    "ApiKey",
    "AuditLog",
    "Blob",
    "Device",
    "DeviceAuthorization",
    "Job",
    "Notification",
    "NotificationPreference",
    "Project",
    "ProjectMember",
    "RefreshToken",
    "SystemSetting",
    "User",
]
