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


class KnowledgeDocPatch(BaseModel):
    """Only what the latest answer changed, not the whole document rewritten.

    The interview used to ask the model to return the COMPLETE knowledge document every turn. That
    made each turn cost as much as the document was long, and the document only grows: by the
    fourteenth turn it was ~28k characters, the model re-emitted all of it to fold in one answer, and
    a single turn took over a minute — three of them per question, worse every turn. This is the fix:
    the model returns only the changes, and code merges them into the stored document.

    Every list here is an **upsert by the item's natural key** — `steps` by `key`, `edge_cases` by
    `condition`, `data_sources` by `ref`, `acceptance_criteria` by `id`, `integrations` by `system`,
    `inputs`/`outputs`/`glossary` by `name`. An item whose key already exists replaces that one (this
    is how a field gets refined or an edge case confirmed); a new key is appended; anything not
    mentioned is left exactly as it was. `task` and `constraints` merge field by field. Open questions
    the answer resolved go in `resolved_open_questions`; genuinely new ones in `new_open_questions`.
    """

    task: TaskInfo | None = None
    constraints: Constraints | None = None
    data_sources: list[SourceRef] = Field(default_factory=list)
    inputs: list[IOItem] = Field(default_factory=list)
    outputs: list[IOItem] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    edge_cases: list[EdgeCase] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    integrations: list[Integration] = Field(default_factory=list)
    glossary: list[IOItem] = Field(default_factory=list)
    new_open_questions: list[str] = Field(default_factory=list)
    resolved_open_questions: list[str] = Field(default_factory=list)


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


class AgentTask(BaseModel):
    """Work the application asks the executor to carry out on the person's machine.

    `inspect` is reading — a folder, a workbook, a version, whether an endpoint answers — and needs
    no authorisation: it is why the agent is attached. `act` changes something and goes through a
    checkpoint, where the person decides in the browser.
    """

    mode: Literal["inspect", "act"] = "inspect"
    kind: Literal[
        "list_dir", "path_exists", "describe_tabular", "read_head", "command_check", "http_check", "other"
    ] = "other"
    targets: list[str] = Field(default_factory=list)  # paths, urls or command names as the person named them
    wants: list[str] = Field(default_factory=list)  # "sheet names", "column headers", "newest file"
    may_upload: bool = False  # true when a sample answers better than a description


class QuestionSpec(BaseModel):
    question: str
    why: str = ""
    expects: Literal["text", "choice", "yes_no", "file"] = "text"
    options: list[str] = Field(default_factory=list)
    target_gate: str = "G1"
    # who must produce the answer. "agent" only when an executor is attached: code downgrades it
    # otherwise, so a session without an agent behaves exactly as before.
    audience: Literal["person", "agent"] = "person"
    task: AgentTask | None = None


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
