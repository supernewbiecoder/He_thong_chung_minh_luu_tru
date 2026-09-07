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

## Kết quả đo được

```
batch │ B1 cận dưới │  B3 tổng  │  Engram   │ B1/Eng │ B3/Eng
    1 │     242.760 │    75.271 │   512.795 │   0,5× │  0,15×
    2 │     462.920 │    99.813 │   512.795 │   0,9× │  0,20×
    5 │   1.124.424 │   173.427 │   512.795 │   2,2× │  0,34×
   10 │   2.226.248 │   296.149 │   512.795 │   4,4× │  0,58×
   20 │   4.430.408 │   541.509 │   512.795 │   8,7× │  1,06×
```

### Bất biến theo *N* — đo riêng, với hợp đồng kích hoạt thật

Bảng trên **không** chứng minh O(1): cột Engram giống nhau vì `expectedDealCount`
bằng 0 ở mọi mức, tức không có gì thay đổi. Phép đo thật nằm ở
`test_gas_khong_doi_theo_so_hop_dong`, nơi *N* hợp đồng được kích hoạt thật:

| *N* | gas | lệch |
|---|---|---|
| 1 | 439.372 | — |
| 5 | 439.393 | +21 gas · 0,005 % |
| 20 | 439.448 | +76 gas · **0,017 %** |

**Không bằng nhau tuyệt đối**, và đừng viết thế trong bài. Không phép đo gas nào
trên EVM cho ra con số y hệt khi trạng thái storage khác nhau.

Điều có ý nghĩa là **so với baseline ở cùng mức tăng *N***:

```
N tăng 20 lần  →  Engram  +0,017 %
                  B3      +619 %      lớn hơn    36.000 lần
                  B1      +1.725 %    lớn hơn   100.000 lần
```

Đó mới là cách phát biểu RQ2 đứng vững trước phản biện.

### Vì sao B1 dùng cận dưới

Execution của B1 trong khung test **tăng theo bậc hai** — chi phí biên là
253.532 · 283.013 · 313.255 · 367.998 khi *n* tăng. Nguyên nhân: Solidity mã hoá
`bytes memory` thêm một lần nữa cho lời gọi ngoài, và mở rộng bộ nhớ tính theo
`3w + w²/512`. **Một giao dịch thật không có khoản này** — calldata đến thẳng.

Nên bảng chỉ dùng **intrinsic** cho B1: 220.416 gas mỗi proof, tuyến tính, và là
chi phí không thể tránh của việc đưa 13.776 byte lên chuỗi. Đó là **cận dưới** —
B1 thật còn đắt hơn.

Dùng cận dưới là chọn hướng **bất lợi cho kết luận của mình**. Nếu Engram vẫn
thắng từ batch 3 khi so với cận dưới của baseline, kết luận vững hơn nhiều.

B3 thì sạch cả hai cột — chi phí biên 23.512–23.520 ổn định, khớp SSTORE 22.100
cộng phụ phí. Calldata của nó nhỏ nên không có hiện tượng trên.

## Hai điểm giao — trình bày trung thực

```bash
forge test --match-test diem_giao -vv
```

Ở batch nhỏ **Engram đắt hơn**:

| So với | Engram rẻ hơn từ | Đo được |
|---|---|---|
| B1 gửi raw calldata | batch ≥ **3** | điểm giao 2,2 |
| B3 chỉ lưu băm | batch ≥ **19** | điểm giao 18,7 |

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

### Kết quả đo được

Quét *N* ở *S*=2, hai epoch:

| *N* | chu kỳ/epoch | biên mỗi hợp đồng | phần cố định |
|---|---|---|---|
| 20 | 1.186,7 × 10⁹ | — | **62,1 %** |
| 50 | 1.862,0 × 10⁹ | 22,51 × 10⁹ | 39,6 % |
| 100 | 2.987,5 × 10⁹ | 22,51 × 10⁹ | 24,7 % |

Biên đo được **22,51 × 10⁹** khớp chính xác mô hình `r × m = 2 × 11,255`. Hồi quy
`f + m·N` từ §I.1.6 được **xác nhận bằng mô phỏng**, không chỉ bằng đo vi mô.

Quét *S* ở *N*=100:

| *S* | số ô | chu kỳ/epoch | phần cố định | NFR-05 |
|---|---|---|---|---|
| 1 | 8 | 2.608,0 × 10⁹ | 13,9 % | đạt |
| 2 | 16 | 2.793,8 × 10⁹ | 24,4 % | vượt |
| 4 | 32 | 3.620,4 × 10⁹ | 39,2 % | vượt |
| 8 | 64 | 5.079,8 × 10⁹ | 56,3 % | vượt |

**Chia nhiều mảnh làm tổng chi phí TĂNG** — 8 mảnh tốn gấp 1,95 lần 1 mảnh, dù
cùng 100 hợp đồng. Nghịch lý: **mạng nhỏ phải chia ít**, vì chia nhỏ nghĩa là trả
chi phí cố định *f* = 45,385 × 10⁹ nhiều lần cho những mảnh gần rỗng.

Ở *N*=100 thì NFR-05 (`D·S_ns ≤ N/20`) cho phép tối đa `S_ns ≤ 1,2` — tức **chỉ 1
mảnh**. Cấu hình mặc định 2 mảnh đã vi phạm, và số đo cho thấy đúng: phần cố định
nhảy từ 13,9 % lên 24,4 %.

Một quan sát phụ đáng ghi: ở *S*=8, số blob mạo danh bị loại giảm từ 10 xuống 5 —
kẻ tấn công nhắm một hợp đồng, và hợp đồng đó chỉ nằm trong một mảnh, nên chia
nhiều mảnh **thu hẹp diện tấn công**. Đó là mặt lợi của việc chia nhỏ, đối trọng
với chi phí cố định.

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
