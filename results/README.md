# results/ — nơi mọi kết quả đo đi về

Mọi script đều neo vào **gốc repo**, không phải thư mục hiện tại. Chạy từ đâu
cũng ghi về đây. Đổi chỗ bằng `RESULTS_DIR=...` hoặc cờ `--out`.

| Tệp | Sinh bởi | Nội dung |
|---|---|---|
| `epochs.csv` | `make run` | mỗi epoch một dòng: chu kỳ, sha256_ops, calldata, phán quyết |
| `e2e_real.csv` | `make e2e-real` | mỗi lần chạy một dòng: seal/prove/verify ms, proof_bytes, kết quả |
| `e2e-<timestamp>/` | `make e2e-real` | `proof.bin` 13.776 B, `vk.bin`, `z0.bin`, `ket_qua.json` |
| `rq2_total_cost.csv` | `make bench-rq` | tổng chi phí theo N, tách ba vế gas / DA / proving |
| `rq3_grid.csv` | `make bench-rq` | lưới (N, S_ns, phần cứng) → có lọt ngân sách 24,16 giờ |
| `rq_provenance.csv` | `make bench-rq` | mỗi cột là ĐO, TÍNH, MÔ HÌNH, NGOẠI SUY hay CHƯA ĐO |

## Đọc `rq_provenance.csv` TRƯỚC khi trích số vào bài

Đó là yêu cầu P0.9 của thầy đưa thẳng vào dữ liệu: phân biệt measured, modelled,
extrapolated. Một con số ở N = 10.000 là **ngoại suy** từ ba điểm đo, không phải
"thí nghiệm ở 10.000 nút".

## `e2e_real.csv` tích luỹ, không ghi đè

Mỗi lần chạy thêm một dòng, nên so được nhiều cấu hình. Quét quy mô sector:

```bash
for n in 16 64 256 1024; do ENGRAM_CHUNKS=$n make e2e-real; done
```

Rồi mở `e2e_real.csv` xem `prove_ms` theo `n_chunks`.

## Thư mục này KHÔNG nằm trong git

`.gitignore` bỏ qua nội dung, giữ lại `README.md` này. Kết quả là dữ liệu của
một lần chạy trên một máy cụ thể — commit vào repo sẽ làm người sau tưởng đó là
số của họ.
