# Đánh giá trợ lý AI (BR-AI-05)

Chạy bằng `python -m app.assistant.evaluate` trên dữ liệu seed mới, với model miễn phí chạy trên máy qua Ollama (`ASSISTANT_PROVIDER=ollama`). Ngày chạy: 2026-10-01.

## Kết quả cuối: `ollama/qwen2.5:7b`, đạt **19/20**

Câu duy nhất trượt (câu 4): model gọi tool *nhu cầu vật tư* thay vì *kiểm tra khả dụng*, nên báo "thiếu 1040 kg thép" trong khi thực tế chỉ thiếu 152 kg. Mọi con số đều lấy từ kết quả tool, nên kiểm tra con số (BR-AI-03) vẫn chấp nhận. Đây là giới hạn của model 7B khi chọn tool, và là lý do câu trả lời của trợ lý cần được đối chiếu với các trang dữ liệu.

## Lịch sử các lần chạy

| Lần | Model | Đạt | Thay đổi trước lần chạy |
| --- | --- | --- | --- |
| 1 | qwen2.5:7b | 18/20 | Bản đầu tiên |
| 2 | qwen2.5:7b | 17/20, lần chạy kế tiếp bị dừng | Nhắc model khi trả lời rỗng; sửa đề câu 17. Một lượt gọi model treo 5 phút làm sập lần chạy |
| 3 | qwen2.5:7b | 18/20 (hai lần liên tiếp, cùng kết quả) | Lỗi model thành 503; prompt liệt kê từng endpoint; mô tả tool rõ hơn |
| 4 | qwen2.5:7b | **19/20** | Tool không tham số bỏ qua tham số thừa |
| — | qwen3 (8B) | chưa hoàn tất | Dừng giữa chừng vì mỗi lượt gọi mất khoảng 1 phút trên máy này |

Kết quả có dao động giữa các lần chạy, kể cả với `temperature=0`; vì vậy mỗi cấu hình được chạy nhiều lần.

## Bảng chi tiết (lần 4)

| # | User | Question | Tools called | Tools | Facts | Grounded | Answer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | demo.manager | Lệnh nào đang trễ hạn và vì sao? | get_order_risks | ✓ | ✓ | ✓ | Lệnh sản xuất PO-2026-00003 đang trễ hạn vì đã quá hạn giao. Lệnh này đã sử dụng 100% thời gian dự kiến nhưng chỉ hoàn thành 33% quy trình sản xuất.  Lệnh sản xuất PO-2026-00004 đang ở trạng thái nguy cơ vì đã sử dụng 92% thời gian dự kiến nhưng chỉ hoàn thành 35% quy trình sản xuất. |
| 2 | demo.manager | Lệnh nào có nguy cơ không kịp hạn giao? | get_order_risks | ✓ | ✓ | ✓ | Lệnh sản xuất có nguy cơ không kịp hạn giao là:  - Lệnh PO-2026-00003: quá hạn giao. - Lệnh PO-2026-00004: đang bị chậm tiến độ. |
| 3 | demo.manager | Tuần này có làm được 150 FRAME-A không? | check_material_availability | ✓ | ✓ | ✓ | Có đủ vật tư để sản xuất 150 FRAME-A. Chi tiết về vật tư:  - STEEL-001: Cần 390.000 kg, có 888.000 kg, thiếu 0 kg. - BOLT-M8: Cần 1200 pcs, có 4040 pcs, thiếu 0 pcs. - PAINT-01: Cần 24.75 l, có 83.70 l, thiếu 0 l.  Bạn có thể tiếp tục lập kế hoạch sản xuất. |
| 4 | demo.manager | Nếu làm 400 FRAME-A thì thiếu vật tư gì, thiếu bao nhiêu? | calculate_material_requirements | ✗ | ✗ | ✓ | Để sản xuất 400 FRAME-A, bạn sẽ thiếu các vật tư sau:  - BOLT-M8: 3200 pcs - PAINT-01: 66 l - STEEL-001: 1040 kg  Bạn cần kiểm tra lại tồn kho hoặc đặt hàng bổ sung các vật tư này. |
| 5 | demo.manager | Cần bao nhiêu kg thép cho 150 FRAME-A? | calculate_material_requirements | ✓ | ✓ | ✓ | Để sản xuất 150 FRAME-A, bạn cần 390 kg thép (STEEL-001). |
| 6 | demo.manager | 120 BRACKET-B cần bao nhiêu bu lông BOLT-M8? | calculate_material_requirements | ✓ | ✓ | ✓ | Để sản xuất 120 BRACKET-B, bạn cần 480 bu lông BOLT-M8. |
| 7 | demo.manager | Work center nào đang là điểm nghẽn? | get_bottlenecks | ✓ | ✓ | ✓ | Work center đang là điểm nghẽn là WC-WELD, với số lượng đơn hàng đang chờ là 100 và có 2 đơn hàng đang ở trạng thái rủi ro. |
| 8 | demo.manager | Trạm hàn đang tồn bao nhiêu đơn vị chờ xử lý? | get_bottlenecks | ✓ | ✓ | ✓ | Trạm hàn (WC-WELD) đang tồn 100 đơn vị chờ xử lý. |
| 9 | demo.warehouse | Vật tư nào đang dưới mức tồn tối thiểu? | get_low_stock_materials | ✓ | ✓ | ✓ | Có hai vật tư đang dưới mức tồn tối thiểu:  1. BOLT-M8 (Bolt M8x20): Dưới mức tồn tối thiểu 4500 pcs còn 4040 pcs, thiếu 460 pcs. 2. STEEL-001 (Steel sheet 2 mm): Dưới mức tồn tối thiểu 1000 kg còn 888 kg, thiếu 112 kg. |
| 10 | demo.warehouse | Thép STEEL-001 đang thiếu bao nhiêu so với mức tối thiểu? | get_low_stock_materials | ✓ | ✓ | ✓ | Thép STEEL-001 đang thiếu 112 kg so với mức tối thiểu. |
| 11 | demo.manager | Lệnh PO-2026-00007 đang ở trạng thái nào? | get_production_order_status | ✓ | ✓ | ✓ | Lệnh sản xuất PO-2026-00007 đang ở trạng thái MATERIAL_SHORTAGE. Hiện tại, tất cả các công đoạn đều đang trong trạng thái PENDING. Due date của lệnh này là 11/10/2026. |
| 12 | demo.manager | PO-2026-00001 đã hoàn thành bao nhiêu sản phẩm đạt? | get_production_order_status | ✓ | ✓ | ✓ | PO-2026-00001 đã hoàn thành 19 sản phẩm đạt. |
| 13 | demo.manager | Lệnh PO-2026-00005 đi được bao nhiêu phần trăm quy trình? | get_production_order_status | ✓ | ✓ | ✓ | Lệnh sản xuất PO-2026-00005 đã hoàn thành 47% quy trình. Trong đó, công đoạn Cutting đã hoàn thành 100%, công đoạn CNC đang ở 40% và công đoạn QC vẫn đang chờ xử lý. |
| 14 | demo.weld | Ở trạm của tôi, PO-2026-00004 đã hàn đạt bao nhiêu chiếc? | get_production_order_status | ✓ | ✓ | ✓ | Trạm của bạn, WC-WELD, đã hàn đạt 38 chiếc khung FRAME-A cho lệnh sản xuất PO-2026-00004. |
| 15 | demo.cnc | Cho tôi xem tình trạng lệnh PO-2026-00004. | get_production_order_status ✗ORDER_NOT_FOUND | ✓ | ✓ | ✓ | Lệnh sản xuất PO-2026-00004 không tồn tại trong hệ thống. |
| 16 | demo.weld | Những lệnh nào đang có rủi ro? | get_order_risks ✗FORBIDDEN | ✓ | ✓ | ✓ | Bạn không có quyền thực hiện hành động này. |
| 17 | demo.cut | Vật tư nào trong kho đang sắp hết? | get_low_stock_materials ✗FORBIDDEN | ✓ | ✓ | ✓ | Bạn không có quyền truy cập vào thông tin về vật tư trong kho. Hãy liên hệ với quản trị viên hệ thống để được hỗ trợ. |
| 18 | demo.warehouse | Kho có đủ vật tư cho 150 FRAME-A không? | check_material_availability | ✓ | ✓ | ✓ | Kho có đủ vật tư cho 150 FRAME-A. Chi tiết như sau: - STEEL-001: Có 888 kg, cần 390 kg. - BOLT-M8: Có 4040 pcs, cần 1200 pcs. - PAINT-01: Có 83.7 l, cần 24.75 l.  Tất cả vật tư đều đủ để sản xuất 150 FRAME-A. |
| 19 | demo.manager | Hủy lệnh PO-2026-00008 giúp tôi. | — | ✓ | ✓ | ✓ | Để hủy lệnh sản xuất PO-2026-00008, bạn hãy truy cập trang chi tiết lệnh sản xuất và thực hiện API POST /api/v1/production-orders/PO-2026-00008/cancel. |
| 20 | demo.warehouse | Nhập thêm 200 kg thép STEEL-001 vào kho giúp tôi. | — | ✓ | ✓ | ✓ | Trang Tồn kho, POST /api/v1/inventory/receipts |
