"""The ingest patch merge: only what changed is folded into the document, deterministically."""

from autoskill.schemas.knowledge import KnowledgeDocModel, KnowledgeDocPatch
from autoskill.services.interview.merge import merge_patch


def _doc() -> KnowledgeDocModel:
    return KnowledgeDocModel.model_validate(
        {
            "task": {"name": "Check invoices", "goal": "flag late ones", "trigger": "", "actor_role": "clerk"},
            "data_sources": [{"ref": "Invoices", "access": ""}],
            "steps": [
                {"key": "open", "title": "Open the sheet", "description": "old description"},
                {"key": "flag", "title": "Flag the row"},
            ],
            "edge_cases": [{"condition": "Sheet missing", "expected_handling": "", "confirmed": False}],
            "open_questions": ["Which folder holds the invoices?", "What counts as late?"],
        }
    )


def test_an_item_with_an_existing_key_is_replaced_not_duplicated():
    patch = KnowledgeDocPatch.model_validate(
        {"steps": [{"key": "open", "title": "Open the latest sheet", "description": "new description"}]}
    )
    merged = merge_patch(_doc(), patch)
    assert len(merged.steps) == 2, "the key already existed — refine in place, do not append"
    opened = next(s for s in merged.steps if s.key == "open")
    assert opened.title == "Open the latest sheet" and opened.description == "new description"


def test_a_new_key_is_appended_and_order_is_kept():
    patch = KnowledgeDocPatch.model_validate({"steps": [{"key": "save", "title": "Save the file"}]})
    merged = merge_patch(_doc(), patch)
    assert [s.key for s in merged.steps] == ["open", "flag", "save"]


def test_unmentioned_content_is_left_exactly_as_it_was():
    # a patch that only touches one edge case must not disturb steps, sources or the other fields
    patch = KnowledgeDocPatch.model_validate(
        {"edge_cases": [{"condition": "Sheet missing", "expected_handling": "halt and tell the person", "confirmed": True}]}
    )
    merged = merge_patch(_doc(), patch)
    assert len(merged.edge_cases) == 1 and merged.edge_cases[0].confirmed is True
    assert [s.key for s in merged.steps] == ["open", "flag"], "steps untouched"
    assert merged.task.name == "Check invoices", "task untouched"


def test_a_retyped_key_still_matches_despite_spacing_and_case():
    patch = KnowledgeDocPatch.model_validate({"data_sources": [{"ref": " invoices ", "access": "shared drive"}]})
    merged = merge_patch(_doc(), patch)
    assert len(merged.data_sources) == 1, "'Invoices' and ' invoices ' are the same source"
    assert merged.data_sources[0].access == "shared drive"


def test_resolved_questions_are_removed_and_new_ones_added():
    patch = KnowledgeDocPatch.model_validate(
        {
            "resolved_open_questions": ["Which folder holds the invoices?"],
            "new_open_questions": ["Which column has the amount?", "What counts as late?"],
        }
    )
    merged = merge_patch(_doc(), patch)
    # the resolved one is gone, the genuinely new one is added, and the duplicate is not added twice
    assert merged.open_questions == ["What counts as late?", "Which column has the amount?"]


def test_task_fields_merge_without_blanking_what_is_known():
    patch = KnowledgeDocPatch.model_validate({"task": {"trigger": "every Monday 8am"}})
    merged = merge_patch(_doc(), patch)
    assert merged.task.trigger == "every Monday 8am"
    assert merged.task.name == "Check invoices" and merged.task.goal == "flag late ones", "omitted fields kept"


def test_constraint_lists_union_and_pii_latches_true():
    doc = _doc()
    doc.constraints.tools_available = ["openpyxl"]
    doc.constraints.pii = False
    patch = KnowledgeDocPatch.model_validate(
        {"constraints": {"tools_available": ["openpyxl", "smtplib"], "pii": True}}
    )
    merged = merge_patch(doc, patch)
    assert merged.constraints.tools_available == ["openpyxl", "smtplib"], "union, no duplicate"
    assert merged.constraints.pii is True


def test_the_input_document_is_not_mutated():
    doc = _doc()
    merge_patch(doc, KnowledgeDocPatch.model_validate({"steps": [{"key": "open", "title": "Changed"}]}))
    assert doc.steps[0].title == "Open the sheet", "merge returns a new doc, leaves the original alone"
