"""
═══════════════════════════════════════════════════════════════════════════════
 provider — DỊCH VỤ NÚT LƯU TRỮ
 [SPEC §A.2 vai trò 2] · [SPEC UC-02, UC-03, UC-04, UC-10]
═══════════════════════════════════════════════════════════════════════════════

 Chạy độc lập. Người bán dung lượng chỉ cần tải thư mục này.

 ── ĐIỀU DỄ HIỂU SAI NHẤT VỀ DỊCH VỤ NÀY ──────────────────────────────────

 Nút KHÔNG BAO GIỜ gửi bundle lên EVM. Bundle đi lên CELESTIA.

 Cả đời một hợp đồng, nút chỉ gửi EVM đúng BA giao dịch:
     registerSealed · activate · claimSettlement

 Nếu 10.000 nút mỗi ngày gửi một giao dịch EVM thì đó chính là đường cơ sở mà
 kiến trúc này bác bỏ — nó chết ở 727 nút. [SPEC §I.1.1]

 ── VÒNG ĐỜI, THEO THỨ TỰ ─────────────────────────────────────────────────

     UC-10  registerProvider    một lần khi gia nhập
     UC-02  nhận chunk, tính lại piece_root, ký biên nhận
     UC-02  niêm phong SeqWide → registerSealed → activate
     UC-03  mỗi deadline: sinh bundle → publish lên Celestia
     UC-04  mất dữ liệu: declareUnavailable TRƯỚC khi deadline mở
     UC-08  claimSettlement lấy thưởng
"""
