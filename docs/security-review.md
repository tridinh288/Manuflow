# Rà soát bảo mật theo B16 (Phase 7)

Mỗi dòng của bảng B16 được đối chiếu với code và một test tự động. Đường dẫn test tính từ `backend/`. Ngày rà soát: 2026-10-01.

## Kết quả

| Vấn đề (B16) | Cách triển khai | Bằng chứng | Kết quả |
| --- | --- | --- | --- |
| Mật khẩu | Hash Argon2 (`core/security.py`), tối thiểu 10 ký tự (`domain/users.py`), không trả về, audit lọc khóa nhạy cảm | `tests/unit/test_security.py::test_b16_password_stored_as_argon2_hash`, `tests/unit/test_users_domain.py::test_b16_password_length_enforced`, `tests/api/test_users.py::test_br_aud_01_user_creation_is_audited_without_password`, `tests/integration/test_audit.py::test_br_aud_05_no_audit_row_contains_secrets_after_logins` | Đạt |
| JWT | HS256, secret ≥ 32 byte, claim `sub/exp/iat/jti`, không có role trong token, hết hạn 30 phút, tải lại user mỗi request | `tests/unit/test_security.py::test_b16_token_has_required_claims_and_no_role`, `tests/api/test_auth.py::test_b16_token_expires_after_30_minutes`, `tests/api/test_auth.py::test_br_auth_04_deactivated_user_token_rejected_on_next_request`, `tests/unit/test_settings.py::test_b16_short_jwt_secret_rejected` | Đạt |
| Phân quyền | Mỗi route khai báo đúng một quy tắc truy cập; phạm vi WORKER trong service, ngoài phạm vi trả 404 | `tests/api/test_access_matrix.py` (quét router + 4 vai trò × mọi endpoint), `tests/unit/test_permissions.py` (đọc bảng B4 từ đặc tả), `tests/api/test_order_reads.py::test_br_auth_03_order_outside_the_workers_scope_is_404_not_403` | Đạt |
| Input không tin cậy | Mọi model request có `extra="forbid"`; trạng thái, số lệnh, tiến độ, người thực hiện do server tính | `tests/unit/test_input_limits.py::test_b16_request_models_reject_unknown_fields` **(mới)**, `tests/api/test_production_orders.py::test_br_auth_01_client_cannot_set_status_or_number` | Đạt |
| Validate | Số lượng là chuỗi thập phân khớp `DECIMAL(18,4)`, chuỗi có độ dài tối đa, mã khớp mẫu, ID và `offset` có cận trên | `tests/unit/test_input_limits.py::test_b16_every_request_field_has_an_explicit_limit` **(mới)**, `tests/api/test_security_inputs.py` **(mới)** | **Sửa trong PR này** (xem phát hiện 1, 2) |
| SQL injection | Chỉ ORM và tham số ràng buộc; `ruff` bật nhóm `S` (gồm `S608`) | `pyproject.toml` (`select` có `"S"`), CI bước `ruff check` | Đạt |
| Lỗi | Một handler duy nhất map lỗi sang B13; lỗi không lường trước trả 500 chung kèm `request_id` | `tests/api/test_error_format.py::test_b13_unhandled_error_returns_500_without_internals`, `tests/integration/test_security_logging.py` **(mới)** | **Sửa trong PR này** (xem phát hiện 3) |
| Dò mật khẩu | Sai 5 lần trong 15 phút thì khóa 15 phút, thông báo chung | `tests/unit/test_login_policy.py::test_br_auth_05_fifth_failure_within_window_locks_for_15_minutes` và các test `br_auth_05` khác | Đạt |
| CORS | Danh sách origin từ biến môi trường; `*` bị từ chối khi khởi động | `tests/unit/test_settings.py::test_b16_wildcard_cors_origin_rejected` | Đạt |
| Bí mật | `.env` trong `.gitignore`; `.env.example` chỉ có giá trị giả; từ chối secret mặc định ngoài `ENV=dev`; lỗi cấu hình không in giá trị secret; skill Git quét bí mật trước commit | `tests/unit/test_settings.py::test_b16_default_jwt_secret_rejected_outside_dev`, `tests/unit/test_settings.py::test_b16_jwt_secret_error_does_not_leak_value` | Đạt |
| Tài khoản DB | API dùng `manuflow_app` (chỉ DML); Alembic dùng `manuflow_migrator` | `tests/integration/test_migrations.py::test_b16_application_user_cannot_run_ddl`, `docker/mysql/init/01-databases-and-users.sh` | Đạt |
| Phụ thuộc | `pip-audit` trong CI | `.github/workflows/ci.yml` bước "pip-audit (B16)" | Đạt |
| Git | `main` bắt buộc qua PR, bắt buộc 2 check CI, nhánh phải cập nhật, cấm force-push | Cài đặt branch protection (kiểm tra bằng `gh api repos/tridinh288/Manuflow/branches/main/protection`) | Đạt, có khuyến nghị (xem dưới) |

Ngoài ra: idempotency lưu fingerprint dạng HMAC có khóa, không lưu body (`tests/unit/test_idempotency_domain.py::test_b16_fingerprint_is_keyed_so_passwords_cannot_be_brute_forced_offline`, `tests/api/test_idempotency.py::test_b16_stored_key_row_holds_no_password`).

## Phát hiện và cách sửa

1. **`offset` quá lớn gây lỗi 500.** `GET /api/v1/users?offset=18446744073709551616` làm MySQL báo lỗi, API trả 500. Client không thấy chi tiết nội bộ, nhưng đây là lỗi validate. Sửa: `Offset` có cận trên `MAX_ID = 2^63 − 1` (`app/schemas/common.py`), giờ trả 422 `VALIDATION_ERROR`.
2. **9 trường ID trong body không có cận trên.** Ví dụ `material_id` của phiếu nhập. Kiểm thử thực tế cho thấy service vẫn trả 422 `*_NOT_FOUND` chứ không lỗi, nhưng giá trị được đưa xuống DB. Sửa: các trường ID trong request có `le=MAX_ID`, bị chặn ngay ở tầng validate. Test quét `test_b16_every_request_field_has_an_explicit_limit` giữ quy tắc này cho endpoint mới.
3. **Log lỗi DB có thể chứa giá trị tham số.** Handler 500 ghi `logger.exception`, và exception của SQLAlchemy mặc định kèm `[parameters: …]`. Một lỗi DB khi INSERT user sẽ đưa hash mật khẩu và username vào log. Sửa: `create_engine(..., hide_parameters=True)` (`app/db/session.py`). Test dùng DB thật, gây lỗi với một giá trị bí mật và kiểm tra giá trị đó không có trong thông điệp lỗi.

Mỗi bản sửa đã được kiểm chứng ngược: gỡ bản sửa thì test tương ứng fail.

## Khuyến nghị cho chủ repo (không tự thay đổi)

- Branch protection của `main` đang để `enforce_admins = false`, nên tài khoản admin có thể bỏ qua quy tắc. Nên bật "Do not allow bypassing the above settings" trong Settings → Branches.

## Ngoài phạm vi (ghi trong README)

Refresh token, HTTPS (do reverse proxy đảm nhiệm khi triển khai thật), SSO, giới hạn tần suất request ngoài cơ chế khóa tài khoản.
