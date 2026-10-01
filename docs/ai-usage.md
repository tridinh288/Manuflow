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

### 5. Merge PR xếp chồng làm GitHub tự đóng PR phụ thuộc (Phase 2, quy trình Git)

- **AI làm:** merge PR #2 bằng `gh pr merge --merge --delete-branch`, trong khi PR #3 dùng nhánh của #2 làm base. Xóa nhánh base qua API khiến GitHub **tự đóng** #3 thay vì tự đổi base của nó.
- **Phát hiện bởi:** `gh pr edit 3 --base main` thất bại với lỗi "Cannot change the base branch of a closed pull request".
- **Sửa:** tạo lại nhánh base tại đúng commit cũ, mở lại #3, đổi base về `main`, rồi xóa nhánh tạm. Không mất commit nào. Với #3 → #4, AI làm theo thứ tự đúng: merge không xóa nhánh → đổi base của PR phụ thuộc → xóa nhánh. Skill `git-pr-workflow` (mục C) đã thêm bước này.
- **PR:** #2, #3; quy trình được sửa trong phase-2/last-admin-guard.

### 6. Test đồng thời pass sai lý do: khóa khóa ngoại thay vì khóa của cơ chế chặn (Phase 2)

- **AI viết:** test C-12 giữ khóa dòng `admin_1`, rồi khẳng định request vô hiệu hóa `admin_2` phải chờ. Actor của request lại chính là `admin_1`, nên dòng audit có FK `actor_user_id = admin_1`, và InnoDB lấy shared lock trên dòng cha khi kiểm tra FK. Request bị chặn **vì khóa ngoại**, không phải vì cơ chế chặn khóa các dòng ADMIN.
- **Phát hiện bởi:** cố tình phá code, bỏ `FOR UPDATE` ở `lock_active_admin_ids`: test đồng thời vẫn pass.
- **Sửa:** dùng actor không có dòng user (`user_id=None`), để test chỉ còn đo khóa ADMIN. Phá lại: bỏ `FOR UPDATE` → 2 test fail; khôi phục → pass. Test race cũng được siết lại, từ chấp nhận cả `["OK", "OK"]` thành bắt buộc đúng một `LAST_ADMIN`.
- **PR:** phase-2/last-admin-guard.

### 7. Lại một test đồng thời pass nhờ khóa khóa ngoại (Phase 3)

- **AI viết:** test cho khóa work center khi gán WORKER. Một transaction giữ khóa dòng work center, rồi test khẳng định request tạo WORKER "phải chờ". Request đó luôn phải chờ, vì INSERT user có FK `work_center_id` lấy shared lock trên dòng cha, **kể cả khi service không khóa**. Đây là cùng một cái bẫy như mục 6: AI đã ghi lại bài học nhưng vẫn lặp lại.
- **Phát hiện bởi:** cố tình phá code, đổi `get_for_update` thành `get`: test vẫn pass.
- **Sửa:** test tái hiện đúng thứ tự gây hại. Transaction giữ khóa đặt `active = 0` nhưng chưa commit, và request gán phải nhận `WORK_CENTER_INACTIVE`. Không có khóa, request đọc snapshot cũ (còn active) và gán thành công, nên test fail. Phá lại: fail; khôi phục: pass.
- **Bài học áp dụng từ giờ:** mọi test đồng thời phải được kiểm chứng bằng cách cố tình phá code, và phải khẳng định **kết quả nghiệp vụ** (mã lỗi, số dòng), không chỉ "có phải chờ hay không".
- **PR:** phase-3/master-data.

### 8. Test đối soát chỉ kiểm một nửa bất biến (Phase 4)

- **AI viết:** test BR-INV-04 cho trường hợp lệch chỉ sửa lén `on_hand_quantity`. Bất biến gồm hai vế: `SUM(on_hand_delta) = on_hand` **và** `SUM(reserved_delta) = reserved`. Một cài đặt chỉ kiểm vế đầu vẫn qua được toàn bộ test.
- **Phát hiện bởi:** cố tình phá code, bỏ so sánh `reserved` trong `reconcile`: 7/7 test vẫn pass.
- **Sửa:** thêm test sửa lén `reserved_quantity`, khẳng định có dòng lệch. Phá lại: fail; khôi phục: pass. Cùng lúc thêm trường hợp vật tư chưa có dòng sổ cái nào (bắt lỗi thiếu `COALESCE`).
- **PR:** phase-4/inventory-reads-reconciliation.

### 9. Hạn giao hàng không được quy về UTC (Phase 5)

- **AI viết:** service tạo lệnh lưu `due_date` đúng như đối tượng nhận từ request. DB lưu đúng giá trị UTC nhờ `UTCDateTime`, nhưng response được dựng từ chính đối tượng đó nên trả `2026-10-02T15:00:00+07:00`, trái với D-23 (mọi thời gian theo UTC).
- **Phát hiện bởi:** test `test_d23_due_date_is_stored_in_utc`, viết cùng lúc với tính năng, fail ở lần chạy đầu.
- **Sửa:** chuẩn hóa `astimezone(UTC)` ngay trong service, cả khi tạo lẫn khi sửa. Cố tình bỏ chuẩn hóa → test fail.
- **PR:** phase-5/orders-state-machine.

### 10. Commit và push dù lint đang fail (Phase 5, quy trình)

- **AI làm:** chạy cổng kiểm tra bằng `docker compose exec … | tail -2 && git commit …`. Ruff báo `Found 1 error` (một dòng quá dài), nhưng mã thoát của chuỗi lệnh là của `tail`, nên commit `81cedab` vẫn được tạo và push. Điều này vi phạm quy tắc "không commit khi lint fail".
- **Phát hiện bởi:** AI đọc output và thấy `Found 1 error` ngay trên dòng commit.
- **Sửa:** không viết lại lịch sử đã push. Thêm commit sửa định dạng ngay sau đó, chạy lại mọi cổng kiểm tra với mã thoát thật (791 passed, exit 0) trước khi mở PR. Skill `git-pr-workflow` (B1) được bổ sung: không nối cổng kiểm tra qua pipe trước `&&`.
- **PR:** phase-5/issue-and-return.

### 11. Ví dụ mẫu trong đặc tả không đủ để kiểm quy tắc (Phase 6)

- **AI viết:** test tiến độ và rủi ro dựa gần như hoàn toàn vào ví dụ B8/B9. Cố tình phá code cho thấy hai cài đặt sai vẫn qua:
  - (a) tính tiến độ công đoạn đã xong bằng `processed / planned` thay vì 1: ở B8, hai công đoạn đã xong tình cờ có `processed = 100`;
  - (b) bỏ sắp xếp theo mức nghiêm trọng: trong test, lệnh quá hạn vốn có hạn sớm hơn.
- **Cũng trong PR này:** test API ban đầu ghép khung thời gian của B9 (tỷ lệ 0,81) với tiến độ 0,66 của B8, ra chênh lệch 0,15 nên đúng ra là ON_TRACK. Kỳ vọng của test sai, không phải code. AI cũng lặp lại cái bẫy token 30 phút hết hạn sau khi đẩy đồng hồ (đã gặp ở D-21).
- **Sửa:** thêm test công đoạn đã xong sau khi phía trước có hàng lỗi (tiến độ vẫn là 1), và test lệnh AT_RISK có hạn muộn hơn lệnh ON_TRACK. Phá lại: cả hai fail.
- **Bài học:** ví dụ trong đặc tả là điểm khởi đầu; mỗi quy tắc cần ít nhất một test mà ở đó cài đặt sai cho kết quả **khác** cài đặt đúng.
- **PR:** phase-6/progress-metrics-risk.

### 12. Test cảnh báo vật tư bỏ sót biên và trường hợp rỗng (Phase 6)

- **AI viết:** test cảnh báo vật tư chỉ có đơn dư rõ ràng (60 ≥ 40) và đơn thiếu rõ ràng. Test điểm nghẽn chỉ dùng lệnh AT_RISK.
- **Phá code cho thấy ba cài đặt sai vẫn qua:** (a) `>` thay cho `>=` (đủ vừa khít thì không được gợi ý); (b) bỏ điều kiện "đơn có dòng vật tư", nên `all()` trên danh sách rỗng gợi ý một đơn không có gì để kiểm; (c) chỉ đếm AT_RISK, bỏ OVERDUE khi tính điểm nghẽn.
- **Sửa:** thêm đơn có tồn vừa đúng bằng nhu cầu, đơn không có dòng vật tư, và cho một trong hai lệnh ở trạm hàn quá hạn. Phá lại: 13/13 mutant fail.
- **Bài học:** mỗi phép so sánh cần một test ngay tại biên, và mỗi `all()` cần một test với danh sách rỗng.
- **PR:** phase-6/bottlenecks-alerts-dashboard.

### 13. Test quét pass vì không quét được gì (Phase 7)

- **AI viết:** test duyệt mọi model request để kiểm tra giới hạn input, dùng `app.routes`. Test pass ngay lần đầu.
- **Phát hiện:** pass ngay lần đầu là dấu hiệu đáng ngờ, nên AI in ra số model quét được: **0**. FastAPI 0.14x gói router con vào `_IncludedRouter`, nên `app.routes` không còn chứa route API. Test ma trận quyền đã gặp đúng chuyện này ở phase trước và dùng `iter_route_contexts`; AI không dùng lại.
- **Sửa:** dùng `iter_route_contexts` và thêm khẳng định "quét được ít nhất 15 model". Bản quét thật tìm ra 9 trường ID không có cận trên. Thử thêm bằng tay lộ ra `offset` quá lớn gây lỗi 500, và log lỗi DB có thể chứa hash mật khẩu. Cả ba đã sửa, xem `docs/security-review.md`.
- **Bài học:** test dạng "duyệt tất cả rồi khẳng định danh sách lỗi rỗng" phải khẳng định luôn rằng nó đã duyệt được thứ gì đó.
- **PR:** phase-7/security-review.

## Rà soát đặc tả

Ở bước rà soát (B20), AI tìm ra 10 điểm mâu thuẫn hoặc còn thiếu trong `docs/requirements.md`. Các điểm này được ghi lại cùng quyết định đã duyệt trong [`decisions.md`](decisions.md).
