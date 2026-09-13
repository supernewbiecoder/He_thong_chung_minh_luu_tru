# 📊 Chiến lược đo trên server — Modular-PoSt

> Mục tiêu: thu tối đa số liệu cho paper trên mỗi giờ server trả tiền.

---

## 1. Mô hình chi phí — cái gì đắt, cái gì rẻ

Biết cái này quyết định thứ tự làm:

| Thao tác | Chi phí | Phụ thuộc | Ghi chú |
|---|---|---|---|
| `bundle-gen` (Nova fold + Spartan) | ~3 phút/bundle | số challenge | **Cache được** — sinh 1 lần, tái dùng mọi batch |
| `--execute` (cycles + prover gas) | khoảng 10–30 phút/điểm với Guest hiện tại | batch size | Rẻ hơn prove nhưng **không nhanh**; N=1 từng mất ~804 giây |
| `--prove` (Groth16) | phút–giờ | batch size | **ĐẮT NHẤT**, RAM lớn, cần Docker |

**Hệ quả chiến lược:** `execute` cho gần hết số liệu cần với chi phí nhỏ. `prove` chỉ cần vài điểm để chứng minh proof size + calldata là hằng số. Đừng bao giờ chạy `prove` trước khi `execute` xong.

### Thủ thuật tiết kiệm lớn nhất (phải ghi vào paper)

Với batch N bundle, host **nhân bản cùng một `ProofBundle` N lần** thay vì sinh N proof phân biệt.

Hợp lệ vì: chi phí verify của `CompressedSNARK` **không phụ thuộc giá trị dữ liệu** — cùng số pairing, MSM, vòng sumcheck. Cycles đo được bằng hệt N proof phân biệt, nhưng tiết kiệm `N × 3 phút` sinh proof. Với N=50 là tiết kiệm **2.5 giờ**.

⚠️ **Bắt buộc nêu trong Section Evaluation** như một measurement methodology note. Nếu reviewer hỏi, chạy thêm một điểm đối chứng với bundle phân biệt (sinh 5 bundle khác nhau, so cycles với 5 bản sao).

---

## 2. Cấu hình server đề xuất

| Giai đoạn | RAM tối thiểu | RAM khuyến nghị | Ghi chú |
|---|---|---|---|
| `execute` | 16 GB | 32 GB | Chủ yếu CPU; nhiều nhân giúp ít |
| `prove` Groth16 | 32 GB (docs SP1) | **64 GB** | Docs SP1 nói ≥32GB cho Docker; verify CompressedSNARK nặng hơn ví dụ mẫu |

**Đề xuất:** một instance ~64GB RAM, 16 vCPU, thuê theo giờ. Ước tính tổng thời gian: **4–8 giờ** cho toàn bộ sweep.

Cần cả **Docker** trên server (Groth16 chạy gnark trong container riêng) và ~30GB đĩa cho circuit artifacts.

Nếu local prove OOM, giữ kết quả execute/cycles và chuyển Groth16 latency sang mục
"chưa đo". Bản simulation-only không dùng hosted prover hoặc API key.

---

## 3. Quy trình 4 phase (đã code trong `sweep.sh`)

### Phase 0 — SMOKE (~5 phút) 🚦 CỔNG CHẶN
```bash
./sweep.sh smoke
```
Sinh 1 bundle nhỏ nhất, chạy execute batch=1. **Nếu fail → dừng, sửa, đừng đốt giờ.**

Đọc cycles ở đây để hiệu chỉnh kỳ vọng:
- **< 100 triệu** → tuyệt, chạy full sweep thoải mái
- **100M – 1 tỷ** → bình thường, prove sẽ lâu; cân nhắc giảm `BATCH_PROVE`
- **> 1 tỷ** → prove có thể OOM/rất lâu. Cân nhắc pivot (mục 5) trước khi chạy prove

### Phase 1 — EXECUTE SWEEP (nhiều giờ với Guest hiện tại) — thu nhiều dữ liệu nhất
```bash
./sweep.sh execute
```
Hai quét, mỗi lần đổi **một** biến:
- **1a. Quét batch** (challenge cố định): bắt đầu batch ∈ {1, 2}; chỉ tăng sau khi đã đo peak RAM → dữ liệu scaling off-chain
- **1b. Quét challenge** (batch = 1): challenges ∈ {1, 3, 10} → dữ liệu **RQ3**

### Phase 2 — PROVE ĐƠN LẺ 🚦 CỔNG CHẶN
Chạy `--prove --batch 1` trước. Nếu OOM → **dừng sweep prove** và giữ ô latency
ở trạng thái chưa đo; không ngoại suy như số đo thật.

### Phase 3 — PROVE SWEEP (nhiều giờ)
```bash
./sweep.sh prove
```
batch ∈ {1, 5, 25}. Chỉ 3 điểm là đủ chứng minh đường nằm ngang (proof size + calldata hằng số).

---

## 4. Số liệu nào trả lời câu hỏi nào

| RQ | Câu hỏi | Số liệu lấy từ | Cột JSONL |
|---|---|---|---|
| **RQ1** | DA tiết kiệm bao nhiêu calldata vs EVM? | `da_payload_bytes` (nếu gửi thẳng lên EVM) vs `evm_calldata_bytes` (thực tế gửi) | Phase 1 + 3 |
| **RQ2** | Chi phí EVM có gần như hằng số khi batch tăng? | `groth16_bytes`, `evm_calldata_bytes` và gas verifier thật theo `batch` | Phase 3 + EVM; execute đơn thuần chưa trả lời |
| **RQ3** | Đánh đổi giữa tiết kiệm on-chain và overhead off-chain? | `cycles`, `prover_gas`, `execute_s`, RAM, `prove_s`, `gen_s` theo `batch`/`challenges` | Phase 1 trả lời phần execute; Phase 3 mới có proving time |

**Kết quả cốt lõi cần thấy:** khi batch tăng 1 → 50, `da_payload_bytes` tăng 50× nhưng `evm_calldata_bytes` **đứng yên** (~260B proof + public values). Đó chính là luận điểm amortization của paper.

Từ đó tính được **điểm hòa vốn**: batch nhỏ thì Groth16 wrapping không đáng (overhead prove lớn hơn tiết kiệm gas); từ batch nào trở lên thì có lãi.

---

## 5. Cổng quyết định — khi nào pivot

| Tình huống | Xử lý |
|---|---|
| Execute OOM | Giảm `--challenges 1`; tăng RAM instance |
| Cycles > 1 tỷ | Xem xét: patch field ops bằng syscall SP1, giảm challenges, hoặc đổi PCS cho secondary |
| Prove OOM ở batch=1 | Giữ execute results; thử lại trên máy local RAM lớn hơn |
| Prove quá lâu (>2h/điểm) | Giảm `BATCH_PROVE` còn {1, 10}; ngoại suy phần còn lại và **nói rõ trong paper** |

---

## 6. Lệnh chạy thực tế

```bash
# ── Trên máy bạn: build image (hoặc build trên server) ──
cd simulation
docker build -t engram-sp1 .

# (tuỳ chọn) đẩy image lên server thay vì build lại
docker save engram-sp1 | gzip > engram-sp1.tar.gz
scp engram-sp1.tar.gz user@server:~/
ssh user@server 'gunzip -c engram-sp1.tar.gz | docker load'

# ── Trên server ──
mkdir -p results

# Phase 0 — CỔNG CHẶN, làm đầu tiên
docker run --rm -v "$(pwd)/results:/results" engram-sp1 /work/sp1_verify/sweep.sh smoke

# Phase 1 — execute sweep (rẻ)
docker run --rm -v "$(pwd)/results:/results" engram-sp1 /work/sp1_verify/sweep.sh execute

# Phase 2+3 — prove (đắt, cần Docker socket cho gnark)
docker run --rm -v "$(pwd)/results:/results" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    engram-sp1 /work/sp1_verify/sweep.sh prove

# ── Mang kết quả về ──
scp -r user@server:~/results ./
```

Tuỳ chỉnh dải quét bằng biến môi trường (không cần sửa script):
```bash
docker run --rm -v "$(pwd)/results:/results" \
    -e BATCH_EXECUTE="1 5 10 50 100" \
    -e CHALLENGES_FIXED=10 \
    engram-sp1 /work/sp1_verify/sweep.sh execute
```

---

## 7. Mẹo tiết kiệm giờ server

1. **Dùng `screen`/`tmux`** — sweep chạy hàng giờ, đứt SSH là mất. `screen -S sweep` rồi chạy trong đó.
2. **Chạy Phase 1 và xem kết quả trước khi thuê tiếp** — nếu cycles hợp lý mới nâng cấp instance cho Phase 3.
3. **Kết quả append ngay vào JSONL** — đứt giữa chừng vẫn giữ được số đã đo, chạy lại chỉ mất phần còn thiếu (bundle cache còn nguyên).
4. **Artifact Groth16 được lưu tự động** (`artifacts/groth16_batchN/`) — mang về để test contract EVM ở nhà, không phải sinh lại trên server.
5. **Đo gas EVM ở nhà** — Foundry/Anvil chạy trên máy thường thoải mái, không tốn giờ server.
