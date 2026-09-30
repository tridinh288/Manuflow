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
