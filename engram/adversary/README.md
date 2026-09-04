# adversary — CHỈ DÙNG KHI MÔ PHỎNG

Hiện thực năm chiến lược tấn công ở [SPEC §J.2], để đo hiệu quả bản sửa thay vì
chỉ lập luận.

| Chiến lược | §J.2 | Cờ tắt bản sửa |
|---|---|---|
| Mạo danh blob | J.2.1 | `blob.enforce_signer=false` |
| Aggregator bỏ mảnh | J.2.2 | `agg.coverage=false` |
| Worker chiếm khe | J.2.3 | `lottery.slot_cap=null` |
| Khách mở rồi bỏ | J.2.4 | `deal.sealing_fee=0` |
| Nghẽn băng thông DA | G.1.5 | — không có bản sửa, đã định giá |
