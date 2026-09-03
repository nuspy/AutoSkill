"""The KnowledgeDoc: structured understanding of a task, built during the interview."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SideEffects = Literal["read_only", "reversible", "irreversible", "unknown"]
RestoreStrategy = Literal["none", "backup_file", "db_transaction", "sandbox_copy", "manual", "unknown"]
KindHint = Literal["deterministic", "generative", "human_gate"]


class TaskInfo(BaseModel):
    name: str = ""
    goal: str = ""
    trigger: str = ""  # when / how often the task happens
    actor_role: str = ""


class SourceRef(BaseModel):
    ref: str  # data source name
    kind: str = "other"
    role: str = ""  # how it is used in the task
    access: str = ""  # where it lives, how to open it
    fields_used: list[str] = Field(default_factory=list)
    sensitivity: str = "internal"


class IOItem(BaseModel):
    name: str
    description: str = ""
    example: str = ""


class Step(BaseModel):
    key: str
    title: str
    description: str = ""
    kind_hint: KindHint = "generative"
    uses: list[str] = Field(default_factory=list)  # source refs
    decision_rules: list[str] = Field(default_factory=list)
    example: str = ""
    side_effects: SideEffects = "unknown"
    restore_strategy: RestoreStrategy = "unknown"
    unclear: bool = False


class EdgeCase(BaseModel):
    condition: str
    expected_handling: str = ""
    source_ref: str | None = None
    confirmed: bool = False


class AcceptanceCriterion(BaseModel):
    id: str
    statement: str
    checkable_by: Literal["human", "automatic", "both"] = "human"


class Integration(BaseModel):
    system: str
    purpose: str = ""
    protocol: str = ""  # e.g. IMAP, SQL, REST, web UI
    credentials_needed: list[str] = Field(default_factory=list)  # names only
    authorizations: str = ""
    contact: str = ""


class Constraints(BaseModel):
    tools_available: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    secrets_needed: list[str] = Field(default_factory=list)
    pii: bool = False


class KnowledgeDocModel(BaseModel):
    task: TaskInfo = Field(default_factory=TaskInfo)
    data_sources: list[SourceRef] = Field(default_factory=list)
    inputs: list[IOItem] = Field(default_factory=list)
    outputs: list[IOItem] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    edge_cases: list[EdgeCase] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    integrations: list[Integration] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    open_questions: list[str] = Field(default_factory=list)
    glossary: list[IOItem] = Field(default_factory=list)
    human_confirmed: bool = False


class GateResult(BaseModel):
    id: str
    title: str
    passed: bool
    detail: str = ""


class SupervisorDecision(BaseModel):
    decision: Literal["proceed", "need_more", "block"]
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    target_gate: str | None = None
    next_question: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)


class QuestionSpec(BaseModel):
    question: str
    why: str = ""
    expects: Literal["text", "choice", "yes_no", "file"] = "text"
    options: list[str] = Field(default_factory=list)
    target_gate: str = "G1"


class MemoryEntryProposal(BaseModel):
    kind: Literal[
        "rationale",
        "business_need",
        "human_procedure",
        "technical_note",
        "integration_note",
        "data_note",
        "decision",
        "lesson_learned",
    ]
    title: str
    body: str
    step_key: str | None = None
    structured: dict = Field(default_factory=dict)


class MemoryExtraction(BaseModel):
    entries: list[MemoryEntryProposal] = Field(default_factory=list)
