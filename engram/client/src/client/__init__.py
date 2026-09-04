"""
═══════════════════════════════════════════════════════════════════════════════
 client — DỊCH VỤ KHÁCH HÀNG
 [SPEC §A.2 vai trò 1] · [SPEC UC-01, UC-02, UC-09]
═══════════════════════════════════════════════════════════════════════════════

 ── ĐIỀU KHÁCH GIỮ SAU KHI XOÁ DỮ LIỆU ───────────────────────────────────

 1.088 byte: piece_root 32 + đường lên provider_root 32×23 + đường lên
 batch_root 32×10. Đó là tất cả những gì cần để kiểm lại vĩnh viễn.

 ── ĐIỀU KHÁCH PHẢI TỰ LO, VÌ GIAO THỨC KHÔNG CƯỠNG CHẾ ĐƯỢC ────────────

 Nếu muốn nhiều bản thì MỖI BẢN PHẢI CÓ piece_root KHÁC NHAU. Bằng không, một
 bên nắm nhiều nút lưu bản thô MỘT LẦN và vẫn qua mọi thách thức — khách trả
 tiền ba bản, nhận độ bền của một. Xem prepare.py.
"""
