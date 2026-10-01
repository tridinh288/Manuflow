# Làm rõ đặc tả đã được duyệt

`docs/requirements.md` là nguồn sự thật. File này ghi các điểm mâu thuẫn hoặc còn thiếu mà AI phát hiện khi rà soát (B20), cùng phương án mặc định đã được chủ dự án duyệt ngày 2026-09-30.
Mã `C-xx` được dùng để không trùng với `D-xx`. Khi chủ dự án chuyển một mục vào bảng quyết định B3, hãy thay mã tương ứng trong code và test.

| Mã | Chạm tới | Vấn đề | Quyết định | Áp dụng từ |
| --- | --- | --- | --- | --- |
| C-01 | BR-AUTH-01, BR-AUTH-04, B16 | JWT không có claim role, nhưng BR-AUTH-01 nói vai trò lấy từ JWT | Danh tính lấy từ `sub` của JWT; vai trò, work center và `active` lấy từ DB ở mỗi request | Phase 2 |
| C-02 | BR-AUTH-02, B13 | Endpoint progress cần hai quyền, nhưng mỗi route chỉ được một dependency | Route khai báo `operation:report`; service kiểm tra thêm `operation:correct` khi có delta âm | Phase 2 |
| C-03 | B12, D-22 | Ghi key ở cuối transaction thì request `plan` trùng đồng thời sẽ trả 409 thay vì response đã lưu | INSERT key đầu tiên trong transaction của service (đứng đầu thứ tự khóa), UPDATE response ở cuối; chỉ lưu response 2xx | Phase 2 |
| C-04 | D-22 | `check-materials` và `cancel` biến động kho nhưng không bắt buộc key | Bắt buộc `Idempotency-Key` cho mọi hành động tạo dòng sổ cái | Phase 5 |
| C-05 | D-10, D-11, D-13, B11 | Chưa quy định ISSUE/RETURN hợp lệ ở trạng thái nào; RETURN ở READY làm sai điều kiện "xuất đủ" | ISSUE chỉ khi READY_TO_PRODUCE; RETURN chỉ khi CANCELLED hoặc COMPLETED | Phase 5 |
| C-06 | BR-AUTH-05, B11 | Không có cột lưu thời điểm bắt đầu cửa sổ 15 phút | Thêm `users.first_failed_login_at`; tài khoản đang khóa trả thông báo chung | Phase 2 |
| C-07 | D-19, BR-MD-04 | Chưa xét vô hiệu hóa work center còn được tham chiếu | Từ chối 409 khi routing ACTIVE hoặc WORKER đang active tham chiếu work center | Phase 3 |
| C-08 | D-22 | Không có job dọn key hết hạn | Key quá 24h coi như không tồn tại và bị xóa khi tra; thêm lệnh CLI dọn thủ công | Phase 2 |
| C-09 | B9 | `time_ratio` chia cho 0 khi `due_date = started_at`; dòng `NOT_STARTED_DUE_SOON` cho MATERIAL_SHORTAGE không bao giờ khớp | Mẫu số ≤ 0 thì `time_ratio = 1`; giữ nguyên dòng dư thừa, ghi chú lại | Phase 6 |
| C-10 | BR-OP-01, BR-OP-03 | Không điều chỉnh được công đoạn đã COMPLETED | Giữ nguyên; ghi vào README như một giới hạn | Phase 6 |
| C-11 | Part A (Quy tắc cứng), skill `git-pr-workflow` | Chủ dự án muốn AI merge PR thay mình | AI được merge **chỉ khi chủ dự án yêu cầu rõ ràng cho đúng PR đó** và CI xanh, bằng `--merge --delete-branch`; cấm `--admin`/`--auto`/`--squash`/`--rebase`. `CLAUDE.md` và skill đã cập nhật (2026-09-30); phần A của `requirements.md` cần được chủ dự án cập nhật ở bản gốc | Ngay |
| C-12 | BR-AUTH, B4, D-17 | Đặc tả không ngăn việc vô hiệu hóa hoặc hạ vai trò ADMIN cuối cùng, khiến hệ thống có thể mất hết quản trị viên | Từ chối 409 `LAST_ADMIN` khi thay đổi làm ADMIN active cuối cùng mất quyền. Service khóa mọi dòng ADMIN active (theo `id`) trước dòng đích, để hai admin hạ nhau cùng lúc được tuần tự hóa | Phase 2 |
| C-13 | D-19, BR-MD-04 | Đọc sát chữ, D-19 chặn vô hiệu hóa sản phẩm còn BOM ACTIVE. Nhưng BOM ACTIVE chỉ chuyển RETIRED khi có phiên bản mới, nên sản phẩm đã có BOM sẽ không bao giờ vô hiệu hóa được | Sản phẩm chỉ bị chặn khi còn lệnh sản xuất đang mở (Phase 5). BOM/routing được giữ nhưng không dùng được nữa (bung BOM → 409 `PRODUCT_INACTIVE`). Điều kiện "BOM ACTIVE tham chiếu" của D-19 chỉ áp dụng cho vật tư | Phase 3 |
| C-14 | BR-MD-02, D-05 | Chưa quy định có được sửa `unit` và `decimal_places` của vật tư hay không; giảm số chữ số lẻ sẽ làm dữ liệu cũ vi phạm quy tắc làm tròn | `unit` và `decimal_places` không sửa được sau khi tạo, giống mã vật tư. PUT chỉ nhận `name` và `minimum_stock` | Phase 3 |
| C-15 | B6, BR-MD-04 | Chưa quy định có được nhập kho cho vật tư đã vô hiệu hóa hay không | RECEIVE bị từ chối (409 `MATERIAL_INACTIVE`); ADJUSTMENT vẫn được phép để kiểm kê hoặc xóa sổ phần tồn còn lại | Phase 4 |

## Ghi chú triển khai

- C-01, C-02 (phần `require` một quyền/route), C-03, C-06, C-08: đã triển khai ở Phase 2.
- Thứ tự khóa toàn cục của B12 được mở rộng: `idempotency_keys` đứng **trước** `document_sequences`, vì dòng key luôn được INSERT đầu tiên trong transaction (C-03).
- Fingerprint của request là HMAC-SHA256 với khóa phía server, vì body có thể chứa mật khẩu (`POST /users`). Nếu dùng hash không khóa, dữ liệu lưu trong DB có thể bị brute-force ngoại tuyến.
- C-12 được chủ dự án duyệt ngày 2026-09-30 và triển khai ở Phase 2.
- C-13, C-14 được chủ dự án duyệt ngày 2026-09-30 ("làm theo kế hoạch đó đi").
- Bảng `inventory` được tạo ở Phase 3 (không đợi Phase 4) để mỗi vật tư có dòng tồn kho bằng 0 ngay khi được tạo (BR-INV-01).
- C-07 hoàn tất ở Phase 3: work center bị chặn vô hiệu hóa khi còn WORKER active hoặc nằm trong routing ACTIVE. Gán WORKER và kích hoạt routing đều khóa dòng work center.
- C-15 được chủ dự án duyệt ngày 2026-10-01. Thứ tự khóa của mọi biến động kho: key idempotency → khóa đọc chung trên dòng vật tư → khóa ghi trên dòng tồn kho. Vô hiệu hóa vật tư và kích hoạt BOM chỉ khóa dòng vật tư, nên không tạo vòng chờ.
