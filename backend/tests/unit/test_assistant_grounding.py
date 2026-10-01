"""BR-AI-03: the final answer may only quote numbers the tools returned."""

from app.assistant.grounding import allowed_numbers, ungrounded_numbers

RISKS = {
    "orders": [
        {
            "production_order": "PO-2026-00004",
            "risk": "AT_RISK",
            "time_ratio": 0.92,
            "workflow_progress": 0.35,
            "message": "Đã dùng 92% thời gian",
        },
        {
            "production_order": "PO-2026-00003",
            "risk": "OVERDUE",
            "time_ratio": 1.0,
            "workflow_progress": 0.43,
            "message": "Lệnh đã quá hạn giao.",
        },
    ]
}
STOCK = {
    "items": [
        {
            "material_code": "STEEL-001",
            "required": "1040.000",
            "available": "888.000",
            "shortage": "152.000",
        }
    ]
}


def check(answer: str, *results: dict, question: str = "") -> list[str]:  # type: ignore[type-arg]
    return ungrounded_numbers(answer, allowed_numbers(question, list(results)))


def test_br_ai_03_numbers_copied_from_tools_are_grounded() -> None:
    assert check("Thiếu 152.000 kg thép: cần 1040.000, còn 888.000.", STOCK) == []
    assert check("Thiếu 152 kg thép (cần 1040 kg).", STOCK) == []  # trailing zeros dropped


def test_br_ai_03_ratios_as_percent_counts_and_order_numbers_are_grounded() -> None:
    answer = "Có 2 lệnh có rủi ro: PO-2026-00004 đã dùng 92% thời gian, mới xong 35% quy trình."
    assert check(answer, RISKS) == []


def test_br_ai_03_numbers_from_the_question_are_grounded() -> None:
    assert (
        check(
            "150 FRAME-A cần 390.000 kg thép.",
            {"required": "390.000"},
            question="Làm được 150 FRAME-A không?",
        )
        == []
    )


def test_br_ai_03_invented_numbers_are_flagged() -> None:
    assert check("Thiếu 160 kg thép, dự kiến xong sau 3 ngày.", STOCK) == ["160", "3"]


def test_br_ai_03_no_tool_result_means_no_number_is_grounded() -> None:
    assert check("Tồn kho còn 500 kg.") == ["500"]


def test_br_ai_03_identifiers_do_not_ground_numbers() -> None:
    result = {"items": [{"material_id": 3, "id": 7, "order_material_id": 12, "shortage": "0"}]}
    assert check("Sẽ xong sau 3 ngày, còn 7 bước.", result) == ["3", "7"]
