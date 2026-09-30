# Nhật ký dùng AI

Công cụ: Claude Code (model Claude Opus 5.5), làm việc theo `CLAUDE.md`. Mỗi phần việc một nhánh và một Pull Request; chủ dự án review và merge.

## Lỗi của AI đã bị phát hiện

Mỗi mục ghi: AI đã viết gì, test hoặc review nào phát hiện, sửa ra sao, PR nào.

### 1. Cấu hình không hợp lệ làm lộ secret vào log (Phase 1)

- **AI viết:** `Settings` (pydantic-settings) kiểm tra `JWT_SECRET` bằng `model_validator`. Khi kiểm tra thất bại, `ValidationError` của pydantic kèm theo **toàn bộ input**, gồm `JWT_SECRET` và các DB URL có mật khẩu. Lỗi này sẽ bị in vào log nếu app khởi động thất bại.
- **Phát hiện bởi:** test `test_b16_jwt_secret_error_does_not_leak_value`, viết cùng lúc với tính năng. Test fail ngay lần chạy đầu.
- **Sửa:** bật `hide_input_in_errors=True` trong `model_config`. Test giữ nguyên, không bị nới lỏng.
- **PR:** phase-1/foundation.

### 2. Test quét quyền có thể pass trên danh sách route rỗng (Phase 2)

- **AI viết:** test BR-AUTH-02 duyệt `app.routes` và lọc các `APIRoute`, rồi khẳng định mỗi route khai báo đúng một quy tắc truy cập. Từ FastAPI 0.142, router được include nằm lồng trong `_IncludedRouter`, nên `app.routes` không còn chứa `APIRoute` nào. Nếu test chỉ khẳng định "không route nào vi phạm", nó sẽ **pass trên danh sách rỗng**: kiểu test khẳng định một hành vi sai mà `CLAUDE.md` đã cảnh báo.
- **Phát hiện bởi:** test thứ hai do AI viết cùng lúc, so khớp danh sách route quét được với bảng endpoint của đặc tả (B13). Test này fail với `{} != {...6 endpoint...}`.
- **Sửa:** dùng API public `fastapi.routing.iter_route_contexts` (trả về đường dẫn đầy đủ và dependency có tính cả cấp router), và thêm khẳng định phải quét thấy ít nhất số endpoint trong bảng đặc tả. Kiểm chứng bằng cách cố tình phá: đổi quyền của `/users` → 10 test fail; bỏ kiểm tra quyền trong `require()` → 9 test fail; bỏ nhãn công khai của `/login` → 2 test fail.
- **PR:** phase-2/permissions-users.

### 3. Fingerprint idempotency là hash không khóa của body có mật khẩu (Phase 2)

- **AI viết:** `request_fingerprint` ban đầu là `SHA-256` của body request. Với `POST /users`, body chứa mật khẩu, nên bảng `idempotency_keys` sẽ lưu một hash không salt suy ra từ mật khẩu. Ai đọc được DB có thể brute-force ngoại tuyến.
- **Phát hiện bởi:** AI tự rà soát theo mục cuối của checklist ("thứ gì nhạy cảm bị lưu/trả về?") trước khi chạy test. Chưa có test nào bắt được lỗi này.
- **Sửa:** dùng HMAC-SHA256 với khóa phía server (dẫn xuất từ `JWT_SECRET` có tách miền). Thêm test `test_b16_fingerprint_is_keyed_so_passwords_cannot_be_brute_forced_offline` và `test_b16_stored_key_row_holds_no_password`.
- **PR:** phase-2/idempotency.

### 4. Test vô nghĩa luôn pass (Phase 2)

- **AI viết:** một test tên `test_c08_key_expires_after_24_hours` kết thúc bằng `assert not False` sau khi nhận ra token hết hạn sau 30 phút. Test này luôn pass và không kiểm tra gì cả.
- **Phát hiện bởi:** AI tự đọc lại diff trước khi chạy test.
- **Sửa:** xóa test đó. C-08 được kiểm tra bởi `test_c08_expired_key_is_treated_as_new` (đăng nhập lại trước mỗi request) và bằng cách cố tình phá `is_expired` → 2 test fail.
- **PR:** phase-2/idempotency.

## Rà soát đặc tả

Ở bước rà soát (B20), AI tìm ra 10 điểm mâu thuẫn hoặc còn thiếu trong `docs/requirements.md`. Các điểm này được ghi lại cùng quyết định đã duyệt trong [`decisions.md`](decisions.md).
