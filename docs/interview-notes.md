# Ghi chú phỏng vấn (B19)

Mỗi câu hỏi trỏ tới code và test thật trong repo. Đường dẫn tính từ `backend/` trừ khi ghi khác. Cách dùng: mở file được nêu, trình bày đoạn code chính, rồi chạy đúng test đó (`docker compose exec api pytest -q <đường dẫn>::<tên test>`).

| Câu hỏi | Câu trả lời nằm ở | Bằng chứng để trình bày |
| --- | --- | --- |
| Vì sao FastAPI, SQLAlchemy, session đồng bộ? | B2 | `app/db/session.py` (engine `REPEATABLE READ`, UTC, `hide_parameters`), `app/db/transaction.py`; một method service: `ProductionOrderService.plan` trong `app/services/production_service.py` |
| Vì sao kiến trúc phân tầng và tầng service? | B14 | Route mỏng `plan_order` trong `app/api/v1/production_orders.py` đặt cạnh `ProductionOrderService.plan`; luật trạng thái thuần trong `app/domain/order_state.py`; test tĩnh `tests/api/test_production_orders.py::test_br_po_02_only_the_production_service_writes_order_status` |
| Bung BOM hoạt động thế nào? | B5, BR-BOM-05 | `app/domain/explode.py`; test 1: `tests/unit/test_explode.py::test_br_bom_05_bolts_58_8_round_up_to_59`, `tests/api/test_bom_explosion.py::test_br_bom_05_b5_example_reproduced_through_the_api` |
| Nhu cầu vật tư được tính và làm tròn thế nào? | D-05 | `quantize_up` trong `app/domain/quantities.py` (hàm làm tròn duy nhất); `tests/unit/test_explode.py::test_d05_quantize_up_always_rounds_up` |
| Giữ hàng hoạt động thế nào? | B6 | `app/domain/reservation.py::decide` (all-or-nothing); test 6: `tests/api/test_order_plan.py::test_d08_plan_with_a_shortage_reserves_nothing_and_reports_every_line`, test 5: `test_br_inv_05_plan_with_enough_stock_reserves_every_line` |
| Làm sao chặn tồn kho âm? | BR-INV-02, D-20 | Kiểm tra ở `app/domain/inventory.py` + `CHECK` trong migration; test 9: `tests/api/test_inventory_adjustments.py::test_br_inv_02_adjustment_below_reserved_is_409_and_nothing_changes`, `tests/integration/test_migrations.py::test_br_inv_02_available_can_never_go_negative_at_db_level`; property test `tests/integration/test_inventory_properties.py` |
| Xử lý giữ hàng đồng thời thế nào? | B12 | Thứ tự khóa (key idempotency → lệnh → dòng vật tư → tồn kho theo `material_id` tăng dần) trong `ProductionOrderService.plan`; test 11: `tests/concurrency/test_plan_concurrency.py::test_b12_two_concurrent_plans_reserve_for_exactly_one_order` |
| Transaction được xử lý thế nào? | B12 | `app/db/transaction.py`; test 23: `tests/api/test_order_plan.py::test_b12_failure_after_reservation_rolls_everything_back` |
| Chặn request trùng thế nào? | D-22 | `app/services/idempotency_service.py` (dòng key được INSERT đầu tiên trong cùng transaction); test 12: `tests/api/test_inventory_receipts.py::test_d22_same_key_replays_and_stock_moves_once`, `tests/concurrency/test_idempotency_concurrency.py::test_d22_concurrent_duplicate_waits_and_gets_the_stored_response` |
| RBAC hoạt động thế nào? | B4 | `app/core/permissions.py`, `app/api/access.py`; test 19, 21: `tests/api/test_access_matrix.py` (quét router + 4 vai trò × mọi endpoint); test 20: `tests/api/test_progress.py::test_br_auth_03_worker_reporting_at_another_work_center_gets_404` |
| Audit log hoạt động thế nào? | B10 | `app/services/audit_service.py`, trigger chặn UPDATE/DELETE, `GET /audit-logs` có bộ lọc (`tests/api/test_audit_logs.py`); test 22: `tests/integration/test_audit.py::test_br_aud_02_audit_row_is_rolled_back_with_its_transaction`, `test_br_aud_05_no_audit_row_contains_secrets_after_logins` |
| Bạn kiểm thử backend thế nào? | B15 | `scripts/rule_coverage.py` (CI fail khi một quy tắc Phase 1–7 không có test); bảng mutation trong mỗi PR; property test Hypothesis; CI trên từng PR (`.github/workflows/ci.yml`) |
| Bạn dùng AI thế nào, và kiểm chứng code của AI ra sao? | Part A, skill Git | `CLAUDE.md`, `.claude/skills/git-pr-workflow/SKILL.md`, lịch sử PR (một phần việc một PR, CI bắt buộc), `docs/ai-usage.md` |
| Khi AI sinh sai logic nghiệp vụ thì sao? | `docs/ai-usage.md` | 13+ trường hợp thật, ví dụ: test pass vì khóa FK chứ không vì logic (mục 6, 7); hạn giao không quy về UTC (mục 9); ví dụ đặc tả không đủ để bắt cài đặt sai (mục 11); test quét pass vì quét 0 model (mục 13) |
| Phát hiện điểm nghẽn thế nào? | B9 | `app/domain/risk.py`, `app/domain/bottleneck.py`, `app/services/dashboard_service.py`; test 18: `tests/unit/test_risk.py`; `tests/api/test_dashboard_overview.py::test_b9_two_at_risk_orders_at_welding_make_it_the_bottleneck` |
| Với một nhà máy thật, bạn sẽ thay đổi gì? | Ngoài phạm vi ở B1 | BOM nhiều cấp, nhiều kho/vị trí, lô và serial, lập lịch theo năng lực, tích hợp ERP, async và refresh token; xem mục "Known limitations" và "Out of scope" của README |

## Câu chuyện nên kể (2 phút)

1. **Bài toán:** biến một yêu cầu sản xuất thành luồng có kiểm soát; mọi biến động kho truy vết được tới người làm.
2. **Quyết định khó nhất:** giữ hàng all-or-nothing dưới tranh chấp. Thứ tự khóa cố định cộng `CHECK` ở DB; test đồng thời hai lệnh 80 và 50 trên tồn 100.
3. **Cách kiểm chứng code AI:** mỗi PR có bảng mutation (cố tình làm sai code, test phải fail). Ví dụ thật: ở Phase 6, ví dụ trong đặc tả không phân biệt được cài đặt đúng và sai; ở Phase 7, property test ban đầu không hề xuất/trả kho lần nào, phát hiện nhờ thống kê của Hypothesis.
4. **Giới hạn trung thực:** không có năng lực máy, không sửa công đoạn đã hoàn thành (C-10), dashboard tính tại chỗ.
