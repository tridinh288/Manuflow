# Nhật ký dùng AI

Công cụ: Claude Code (model Claude Opus 5.5), làm việc theo `CLAUDE.md`. Mỗi phần việc một nhánh và một Pull Request; chủ dự án review và merge.

## Lỗi của AI đã bị phát hiện

Mỗi mục ghi: AI đã viết gì, test hoặc review nào phát hiện, sửa ra sao, PR nào.

### 1. Cấu hình không hợp lệ làm lộ secret vào log (Phase 1)

- **AI viết:** `Settings` (pydantic-settings) kiểm tra `JWT_SECRET` bằng `model_validator`. Khi kiểm tra thất bại, `ValidationError` của pydantic kèm theo **toàn bộ input**, gồm `JWT_SECRET` và các DB URL có mật khẩu. Lỗi này sẽ bị in vào log nếu app khởi động thất bại.
- **Phát hiện bởi:** test `test_b16_jwt_secret_error_does_not_leak_value`, viết cùng lúc với tính năng. Test fail ngay lần chạy đầu.
- **Sửa:** bật `hide_input_in_errors=True` trong `model_config`. Test giữ nguyên, không bị nới lỏng.
- **PR:** phase-1/foundation.

## Rà soát đặc tả

Ở bước rà soát (B20), AI tìm ra 10 điểm mâu thuẫn hoặc còn thiếu trong `docs/requirements.md`. Các điểm này được ghi lại cùng quyết định đã duyệt trong [`decisions.md`](decisions.md).
