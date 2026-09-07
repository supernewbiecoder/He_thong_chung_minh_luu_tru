# Sổ tay đo đạc

Bám ba câu hỏi nghiên cứu. Mỗi phép đo ghi rõ **đo được gì** và **không đo được gì**,
vì phần Evaluation của một bài báo sống chết ở chỗ phân biệt hai thứ đó.

```
RQ1  Bảo đảm soundness và completeness khi proof payload nằm ngoài settlement chain?
RQ2  Khi nào zkVM wrapping làm giảm TỔNG chi phí, thay vì chỉ giảm gas?
RQ3  Điểm tối ưu giữa batch size, sharding, proving hardware, DA latency,
     settlement deadline là gì?
```

---

# Chuẩn bị một lần

```bash
cd ~/engram-sim && git pull
export FOUNDRY_DIR="$HOME/engram-sim/.foundry"
export PATH="$FOUNDRY_DIR/bin:$PATH"
cd chain && forge install foundry-rs/forge-std --no-git
```

Ghi lại ba thứ này — **gas phụ thuộc cả ba**, không nêu thì không ai lặp lại được:

```bash
forge --version                     # Foundry 1.8.1
grep -E 'solc|optimizer' foundry.toml
```

---

# RQ1 — Soundness và completeness

RQ1 **không đo bằng con số**, mà bằng *tấn công nào bị chặn*. Cách trình bày mạnh
nhất là một bảng: mỗi hàng một tấn công, mỗi cột trạng thái trước và sau.

```bash
cd ~/engram-sim
make test-py
cd chain && forge test --match-contract EngramManagerTest -vv
```

## Bảng cho bài báo

| Tấn công | Chặn bởi | Test |
|---|---|---|
| Kẻ ngoài mạo danh blob của nút khác | trường `signer` share v1, đồng thuận Celestia áp đặt | `test_blob_mao_danh_bi_loai` |
| Host bỏ sót hợp đồng khỏi danh sách kỳ vọng | `snapshot_id` đối chiếu sổ thành viên on-chain | `test_bot_mot_muc_bi_chan` |
| Host đổi thứ tự sổ | sổ là **chuỗi**, không phải tập hợp | `test_doi_thu_tu_bi_chan` |
| Guest chỉ xét một phần rồi báo xong | `numVerified == expectedDealCount` | `test_tu_choi_khi_chua_xet_het` |
| Aggregator dùng ảnh chụp bịa | `snapshot_id` ghim on-chain | `test_tu_choi_snapshot_sai` |
| Danh sách quyết toán không có trên DA | tuple Blobstream phải trỏ `results_data_root` | `test_tu_choi_khi_manifest_khong_co_tren_da` |
| Host sinh khoá xác minh yếu | `storage_vk_digest` so hằng số ghim | `test_tu_choi_khoa_xac_minh_la` |
| Cướp phần thưởng của aggregator | `submitter` trong public values | `test_tu_choi_khi_submitter_khong_khop` |
| Phát lại bằng chứng epoch cũ | chuỗi trạng thái + thứ tự epoch | `test_tu_choi_epoch_sai_thu_tu` |
| Worker giàu chiếm hết ô | trần thích ứng `max(5 %, r/n)` | `test_du_worker_thi_tran_chan_duoc_ke_giau` |
| Worker rời mạng, ô không được phủ | đình chỉ 3 lần lỡ, 8 deadline | `test_worker_bo_viec_lien_tiep_thi_bi_dinh_chi` |

## Không chứng minh được ở đây

**Rằng đồng thuận Celestia thật sự áp đặt trường `signer`.** `da-mock` tự điền
trường đó. Đây là nền của hàng đầu tiên trong bảng, nên phải kiểm ở giai đoạn 2
(`docs/KIEM_THU.md`) trước khi tuyên bố trong bài.

**Rằng SP1 sound.** Bản này dùng mô hình chi phí. Bảng trên chứng minh *giao thức
xung quanh* đúng, không chứng minh hệ chứng minh đúng.

---

# RQ2 — Khi nào giảm TỔNG chi phí

Đây là phép đo trung tâm, và chữ **tổng** là chỗ dễ sai nhất.

## Ba thành phần, đừng bỏ sót cái nào

```
tổng chi phí = gas on-chain  +  phí DA  +  chi phí proving off-chain
                  đo được        đo được       KHÔNG đo được (SP1)
```

Bài chỉ nói về gas là trả lời hụt RQ2. Phải nêu cả ba, kể cả cái không đo được.

## Đo gas

```bash
cd ~/engram-sim/chain
forge test --match-contract BaselinesTest -vv
```

Bốn phương án, quét batch 1 · 2 · 5 · 10 · 20:

| | Là gì |
|---|---|
| **B1** | gửi toàn bộ raw proof lên EVM |
| **B2** | xác minh Spartan trực tiếp trên EVM — **không có số**, xem dưới |
| **B3** | chỉ lưu băm mỗi proof |
| **B4** | Engram |

**Con số phải là intrinsic + execution.** Foundry chỉ đo execution; phần
intrinsic — 21.000 cộng 16 gas mỗi byte calldata khác 0 — với B1 là **áp đảo**,
vì 13.776 byte mỗi proof đã là 220.416 gas chỉ để đưa dữ liệu lên chuỗi. Bộ đo
đã cộng sẵn cả hai.

**B2 không có số, và đó là kết quả chứ không phải thiếu sót.** Xác minh Spartan
trong Solidity gồm hàng nghìn phép toán trường và nhiều lần MSM — ước tính hàng
chục triệu gas cho *một* proof, tức vượt trần block ngay ở batch 1. Chính điều đó
là lý do bài toán này tồn tại.

## Hai điểm giao — trình bày trung thực

```bash
forge test --match-test diem_giao -vv
```

Ở batch nhỏ **Engram đắt hơn**:

| So với | Engram rẻ hơn từ |
|---|---|
| B1 gửi raw calldata | batch ≥ **3** |
| B3 chỉ lưu băm | batch ≥ **23** |

Nêu thẳng. Nó cho thấy đóng góp là **tính mở rộng**, không phải rẻ tuyệt đối, và
nhất quán với §I.1.5 — mạng cần 140 hợp đồng trên L2 mới hoà vốn. Hai con số cùng
nói một điều, và người phản biện sẽ tin bảng số hơn khi thấy bạn không giấu chỗ dở.

## Đo phần Groth16

```bash
forge test --match-test gas_day_du -vv
```

Cho con số **có phép ghép cặp thật**. `PairingCostVerifier` chạy đúng đường tính
toán Groth16 bằng điểm sinh hợp lệ trên đường cong; kết quả ghép cặp vô nghĩa
nhưng gas là thật, vì `ecPairing` tốn đúng bằng nhau dù trả về 1 hay 0.

Nhờ vậy đo được con số đầy đủ mà **không cần sinh bằng chứng SP1** — việc đòi hàng
chục GiB RAM.

## Đo phí DA

```bash
cd ~/engram-sim && make run
```

Cột `sha256_ops` và số share trong `results/epochs.csv`. Phí lý thuyết: 29 share ·
183.784 gas · 367,6 utia ≈ **0,00024 $** mỗi blob.

Phí **thật** cần Mocha — `docs/KIEM_THU.md` giai đoạn 2.

---

# RQ3 — Điểm tối ưu

Năm biến, và chúng ràng buộc nhau. Mô phỏng in ra ba trong năm mỗi lần chạy.

```bash
make run N_DEALS=20 N_EPOCHS=3
```

## Quét từng biến

**Batch size** — bao nhiêu hợp đồng mỗi epoch:

```bash
for n in 20 50 100 200; do make run N_DEALS=$n N_EPOCHS=2; done
```

**Sharding** — NFR-05 nói `D·S_ns ≤ N/20`:

```bash
for s in 1 2 4 8; do make run N_DEALS=100 N_SHARDS=$s N_EPOCHS=2; done
```

Nghịch lý cần kiểm: **mạng nhỏ phải chia ít**, vì chia nhỏ nghĩa là trả chi phí cố
định *f* = 45,385 × 10⁹ nhiều lần cho những mảnh gần rỗng.

**Proving hardware** — `c_sha` quét sẵn ba giá trị mỗi lần chạy. Cột `sha_cycles`
trong CSV.

**DA latency và settlement deadline** — quan hệ đã có công thức, mô phỏng in ra:

```
t_prove ≤ W < t_seal + t_prove          bất đẳng thức an toàn
t_worker + t_agg < L · t_epoch          bất đẳng thức tính sống
n_workers ≥ S_ns · r · (nghỉ + 1)       ràng buộc xoay vòng — 224 ở N=10.000
```

## Ràng buộc chặt nhất

| Ràng buộc | Cần | Từ đâu |
|---|---|---|
| Trần khe có tác dụng | 40 worker | *r*/0,05 |
| **Xoay vòng không nghẽn** | **224 worker** | *S·r·*(nghỉ+1) |
| Cầu dao an toàn | 224 worker | cùng công thức |

**Xoay vòng chặt hơn trần khe 5,6 lần.** Định cỡ mạng theo 40 là định cỡ theo ràng
buộc yếu nhất, và mạng nghẽn ở tầng worker trước khi ai kịp lo về tập trung cọc.

## Không đo được

`t_worker` và `t_agg` cần SP1 — máy 37 GiB không chạy nổi. Con số 224 là **ước
lượng** suy từ 192 × 10⁹ chu kỳ mỗi ô và tốc độ prover giả định. Ghi rõ là ước
lượng, đừng ghi như số đo.

---

# Chạy demo

Thứ tự này cho người xem thấy hệ thống sống, trong khoảng 5 phút.

```bash
# ① Mã khớp đặc tả, và hệ chạy — 2 giây, không cần mạng
make check

# ② Kiến trúc dịch vụ dựng được — 9 container
make sim

# ③ Bốn trạng thái nút, và kẻ tấn công bị chặn
make run N_DEALS=20 N_EPOCHS=3
```

Kết quả `make run` đọc như sau:

```
epoch 1: PASS=17 FAIL=2 ABSENT=1 · 10 blob mạo danh bị loại · calldata 652 B
```

| Thấy gì | Nghĩa là |
|---|---|
| `PASS=17` | nút thật, bằng chứng đúng |
| `FAIL=2` | một nút mất dữ liệu im lặng, một nút tự khai |
| `ABSENT=1` | nút offline — **được chứng minh vắng mặt**, không phải bị khai |
| `10 blob mạo danh bị loại` | lọc theo người ký đang chạy |
| `calldata 652 B` **ở mọi epoch** | bề mặt on-chain cố định |

Dòng cuối là điều bài báo tuyên bố, và nó **không đổi** giữa các epoch.

---

# Thứ tự nên làm

| | Việc | Thời gian | Được gì |
|---|---|---|---|
| 1 | `forge test --match-contract BaselinesTest -vv` | 2 phút | **Bảng chính của phần Evaluation** |
| 2 | `forge test --match-test gas_ -vv` | 1 phút | Gas đầy đủ, gỡ dấu `MỞ` khỏi Groth16 |
| 3 | `make run` các mức N và S | 10 phút | Số liệu RQ3 |
| 4 | `make check` + bảng tấn công | 5 phút | Bảng RQ1 |
| 5 | Mocha giai đoạn 2 | vài giờ | **Xác nhận trường `signer`** — nền của RQ1 |

Việc 5 là việc duy nhất cần mạng, và cũng là việc duy nhất đóng được giới hạn nặng
nhất còn lại.
