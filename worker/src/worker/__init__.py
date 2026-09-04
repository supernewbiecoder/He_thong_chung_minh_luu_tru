"""
═══════════════════════════════════════════════════════════════════════════════
 worker — DỊCH VỤ XÁC MINH MỘT MẢNH
 [SPEC §A.2 vai trò 3] · [SPEC UC-05] · [SPEC §E.4]
═══════════════════════════════════════════════════════════════════════════════

 Một worker xử lý ĐÚNG MỘT Ô trong lưới (deadline × mảnh). Nó không biết và
 không cần biết gì về các deadline khác hay các mảnh khác. Đó là cách công việc
 O(N) được chia cho hàng trăm máy.

 ── BỐN BƯỚC, VÀ THỨ TỰ LÀ BẮT BUỘC ──────────────────────────────────────

   ① xổ số   trúng ô (deadline, mảnh) nào?         lottery.py
   ② đọc DA  toàn bộ namespace của mảnh, cửa sổ W   da_client.py
   ③ lọc     F0–F3 rồi LỌC THEO NGƯỜI KÝ            engram_common.blob
   ④ chứng minh  phủ đầy đủ → merge-join → verdict  verify.py

 Bước ③ đặt SAU bước ② và TRƯỚC bước ④ là bắt buộc. Đảo ④ lên trước ③ thì mỗi
 blob rác tốn 11,255e9 chu kỳ, và kẻ tấn công trả 0,00009 $ để đốt hàng phút
 zkVM. [SPEC §G.1.4]
"""
