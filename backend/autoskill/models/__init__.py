"""ORM models. Import all modules so Alembic and create_all see every table."""

from autoskill.models.api_key import ApiKey
from autoskill.models.audit import AuditLog
from autoskill.models.blob import Blob
from autoskill.models.data_source import DataSource
from autoskill.models.device import Device, DeviceAuthorization
from autoskill.models.hub import Category, Favorite, Installation, SkillRepo
from autoskill.models.improvement import ImprovementProposal
from autoskill.models.interview import InterviewMessage, InterviewSession, KnowledgeDoc
from autoskill.models.job import Job
from autoskill.models.llm_provider import LlmProvider
from autoskill.models.mcp import McpServer, McpServerVersion
from autoskill.models.memory import SkillMemoryEntry
from autoskill.models.notification import Notification, NotificationPreference
from autoskill.models.procedure import Procedure, ProcedureStep
from autoskill.models.project import Project, ProjectMember
from autoskill.models.review import Authorization, ReviewDecision, ReviewRequest, VersionTransition
from autoskill.models.skill import Skill
from autoskill.models.skill_version import LibraryComponent, SkillDependency, SkillVersion, StepDefinition
from autoskill.models.system_setting import SystemSetting
from autoskill.models.trial import Checkpoint, Run, RunAnnotation, RunStep, StepDiscussion, TrialSession
from autoskill.models.usage import ProjectUsageDaily
from autoskill.models.user import RefreshToken, User

__all__ = [
    "ImprovementProposal",
    "McpServer",
    "McpServerVersion",
    "Category",
    "Favorite",
    "Installation",
    "SkillRepo",
    "Authorization",
    "ReviewDecision",
    "ReviewRequest",
    "VersionTransition",
    "Checkpoint",
    "Run",
    "RunAnnotation",
    "RunStep",
    "StepDiscussion",
    "TrialSession",
    "SkillVersion",
    "StepDefinition",
    "LibraryComponent",
    "SkillDependency",
    "ApiKey",
    "AuditLog",
    "Blob",
    "DataSource",
    "Device",
    "DeviceAuthorization",
    "InterviewMessage",
    "InterviewSession",
    "KnowledgeDoc",
    "Job",
    "LlmProvider",
    "SkillMemoryEntry",
    "Notification",
    "NotificationPreference",
    "Procedure",
    "ProcedureStep",
    "Project",
    "ProjectMember",
    "Skill",
    "SystemSetting",
    "ProjectUsageDaily",
    "RefreshToken",
    "User",
]
