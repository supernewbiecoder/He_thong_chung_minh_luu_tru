# Kết quả đo

Mọi con số ở đây **đã đo được**, kèm lệnh tái lập và điều kiện đo. Khi viết bài,
lấy từ đây thay vì lục lại cửa sổ terminal.

**Môi trường:** Foundry 1.8.1 · solc 0.8.24 · optimizer 200 runs ·
`PairingCostVerifier` (đường tính toán Groth16 thật) · Python 3.11.

---

## 1 · Gas on-chain

```bash
make attacks        # 16 test Solidity
make baselines      # so sánh 4 phương án
```

### Con số chính

| | Execution | Intrinsic | **Tổng** |
|---|---|---|---|
| Epoch đầu tiên | 475.776 | 34.888 | 510.664 |
| **Epoch ổn định** | **439.372** | **34.888** | **474.260** |

**Bài báo nên dùng con số ổn định.** Một mạng chạy liên tục thì mọi epoch đều là
epoch ổn định; epoch đầu chỉ xảy ra đúng một lần. Chênh **36.404 gas** là chi phí
ghi lần đầu vào ô nhớ lạnh — `currentStateRoot` và `epochs[1]`.

`Intrinsic` không do Foundry đo; nó là `21.000 + 844 B × 16`. Công thức coi mọi
byte khác 0 — đúng với Groth16 thật, và **ước cao hơn** so với `new bytes(356)`
toàn số 0 trong test, tức lệch bất lợi cho Engram.

### Phân rã

| Thành phần | Gas | Cách đo |
|---|---|---|
| Logic hợp đồng | 274.836 | `MockVerifier`, chỉ kiểm độ dài |
| Xác minh Groth16 | **200.940** | hiệu số với `PairingCostVerifier` |
| Intrinsic calldata | 34.888 | 21.000 + 844 × 16 |

Chi phí ghép cặp đo được **200.940** so với ước lượng lý thuyết 193.300
(`ecPairing` 4 cặp 181.000 + 2 `ecMul` 12.000 + `ecAdd` 300) — lệch 3,9 %, phần
dư là mã Solidity bao quanh.

### Giá của việc vá ba lỗ phản biện

| | Logic hợp đồng |
|---|---|
| Trước khi vá | 244.444 |
| Sau khi vá | 274.836 |
| **Chênh** | **+30.392 gas · +12,4 %** |

Đó là giá của `membershipLog`, `activeDealCount`, và ba phép kiểm mới
(`snapshot_id`, `numVerified`, `results_data_root`). **Bảo mật không miễn phí, và
đây là mức cụ thể** — con số đáng nêu, vì nó cho thấy các phép kiểm là thật chứ
không phải khẩu hiệu.

---

## 2 · Bất biến theo *N* — RQ2

```bash
forge test --match-test gas_khong_doi -vv
```

*N* hợp đồng được **kích hoạt thật** để `expectedDealCount` on-chain bằng *N*.

| *N* | Gas | Lệch |
|---|---|---|
| 1 | 439.372 | — |
| 5 | 439.393 | +21 · 0,005 % |
| 20 | 439.448 | +76 · **0,017 %** |

**Đừng viết "gas không đổi".** Không phép đo gas nào trên EVM cho ra con số y hệt
khi trạng thái storage khác nhau. Cách phát biểu đứng vững:

> Chi phí xác minh on-chain tăng **0,017 %** khi số hợp đồng tăng **20 lần**, so
> với 619 % và 1.725 % của hai đường cơ sở — chênh lệch bốn tới năm bậc độ lớn.

---

## 3 · So với đường cơ sở — RQ2

```bash
make baselines
```

| batch | B1 cận dưới | B3 tổng | Engram | B1/Eng |
|---|---|---|---|---|
| 1 | 242.760 | 75.271 | 474.260 | 0,5× |
| 2 | 462.920 | 99.813 | 474.260 | 1,0× |
| 5 | 1.124.424 | 173.427 | 474.260 | 2,4× |
| 10 | 2.226.248 | 296.149 | 474.260 | 4,7× |
| 20 | 4.430.408 | 541.509 | 474.260 | 9,3× |

**Điểm giao: batch 2 với B1, batch 18 với B3.**

Ở batch nhỏ Engram đắt hơn. Nêu thẳng — nó cho thấy đóng góp là **tính mở rộng**,
không phải rẻ tuyệt đối, và nhất quán với §I.1.5 (140 hợp đồng để hoà vốn trên L2).

### Vì sao B1 dùng cận dưới

Execution của B1 trong khung test tăng **bậc hai** (biên 253.532 → 367.998) vì
Solidity mã hoá `bytes memory` thêm một lần cho lời gọi ngoài, và mở rộng bộ nhớ
tính theo `3w + w²/512`. Giao dịch thật không có khoản này.

Nên bảng chỉ lấy **intrinsic** cho B1 — 220.416 gas mỗi proof, tuyến tính, không
tránh được. Đó là cận dưới; B1 thật còn đắt hơn. Chọn hướng **bất lợi cho kết
luận của mình** thì kết luận vững hơn.

B2 (xác minh Spartan trực tiếp trên EVM) **không có số**, và đó là kết quả: ước
tính hàng chục triệu gas cho *một* proof, vượt trần block ngay ở batch 1.

### Giảm dữ liệu on-chain — RQ1 phần định lượng

| batch | raw | on-chain | giảm |
|---|---|---|---|
| 1 | 13.776 B | 844 B | 16× |
| 10 | 137.760 B | 844 B | 163× |
| 100 | 1,38 MB | 844 B | 1.632× |
| 1.000 | 13,78 MB | 844 B | **16.322×** |

---

## 4 · Chi phí chứng minh — RQ3

```bash
for n in 20 50 100; do make run N_DEALS=$n N_EPOCHS=2; done
for s in 1 2 4 8; do make run N_DEALS=100 N_SHARDS=$s N_EPOCHS=1; done
```

### Quét *N* — xác nhận hồi quy `f + m·N`

| *N* | chu kỳ/epoch | biên mỗi hợp đồng | phần cố định |
|---|---|---|---|
| 20 | 1.186,7 × 10⁹ | — | **62,1 %** |
| 50 | 1.862,0 × 10⁹ | 22,51 × 10⁹ | 39,6 % |
| 100 | 2.987,5 × 10⁹ | 22,51 × 10⁹ | 24,7 % |

Biên **22,51 × 10⁹** khớp chính xác `r × m = 2 × 11,255`. Hồi quy đo vi mô ở
§I.1.6 **đứng vững ở mức hệ thống**.

### Quét *S* — xác nhận NFR-05

| *S* | số ô | chu kỳ/epoch | phần cố định | NFR-05 |
|---|---|---|---|---|
| 1 | 8 | 2.608,0 × 10⁹ | 13,9 % | đạt |
| 2 | 16 | 2.793,8 × 10⁹ | 24,4 % | vượt |
| 4 | 32 | 3.620,4 × 10⁹ | 39,2 % | vượt |
| 8 | 64 | 5.079,8 × 10⁹ | 56,3 % | vượt |

**Chia 8 mảnh tốn gấp 1,95 lần chia 1 mảnh**, cùng 100 hợp đồng. Nghịch lý: mạng
nhỏ phải chia ít, vì chia nhỏ là trả chi phí cố định *f* nhiều lần cho những mảnh
gần rỗng.

Nhưng ở *S*=8, blob mạo danh bị loại giảm từ 10 xuống 5 — chia nhiều mảnh **thu
hẹp diện tấn công**. RQ3 vì thế là bài toán tối ưu hai chiều, không phải một chiều.

### Ràng buộc quy mô

| Ràng buộc | Cần | Nguồn |
|---|---|---|
| Trần khe có tác dụng | 40 worker | *r*/0,05 |
| **Xoay vòng không nghẽn** | **224 worker** | *S·r·*(nghỉ+1) |
| Cầu dao an toàn | 224 worker | cùng công thức |

Xoay vòng chặt hơn trần khe **5,6 lần**. Con số 224 là **ước lượng** — suy từ
192 × 10⁹ chu kỳ mỗi ô và tốc độ prover giả định, vì `t_worker` cần SP1 để đo.

---

## 5 · Tấn công bị chặn — RQ1

```bash
make attacks        # 6 bộ test Python + 16 test Solidity
```

| Tấn công | Chặn bởi | Test |
|---|---|---|
| Kẻ ngoài mạo danh blob | trường `signer` share v1 | `test_blob_mao_danh_bi_loai` |
| Host bỏ sót hợp đồng | `snapshot_id` ↔ sổ thành viên | `test_bot_mot_muc_bi_chan` |
| Host đổi thứ tự sổ | sổ là chuỗi, không phải tập hợp | `test_doi_thu_tu_bi_chan` |
| Guest xét thiếu rồi báo xong | `numVerified == expectedDealCount` | `test_tu_choi_khi_chua_xet_het` |
| Ảnh chụp bịa | `snapshot_id` ghim on-chain | `test_tu_choi_snapshot_sai` |
| Danh sách quyết toán không có trên DA | tuple Blobstream ↔ `results_data_root` | `test_tu_choi_khi_manifest_khong_co_tren_da` |
| Khoá xác minh yếu | so hằng số ghim | `test_tu_choi_khoa_xac_minh_la` |
| Cướp phần thưởng aggregator | `submitter` | `test_tu_choi_khi_submitter_khong_khop` |
| Phát lại epoch cũ | chuỗi trạng thái + thứ tự | `test_tu_choi_epoch_sai_thu_tu` |
| Worker giàu chiếm ô | trần thích ứng | `test_du_worker_thi_tran_chan_duoc_ke_giau` |
| Worker rời mạng | đình chỉ 3 lỡ / 8 deadline | `test_worker_bo_viec_lien_tiep_thi_bi_dinh_chi` |
| Cầu dao thành công cụ DoS | ngưỡng 224 worker | `test_mang_nho_thi_khong_nha` |

---

## 6 · Mô phỏng đầu-cuối

```bash
make run N_DEALS=20 N_EPOCHS=3
```

```
epoch 1: PASS=17 FAIL=2 ABSENT=1 · 10 blob mạo danh bị loại · calldata 652 B
epoch 2: PASS=17 FAIL=2 ABSENT=1 · ...
epoch 3: PASS=17 FAIL=2 ABSENT=1 · ...
```

Bốn trạng thái nút, mỗi cái do một nguyên nhân khác: nút thật · mất dữ liệu im
lặng · mất dữ liệu tự khai · offline. `ABSENT` là kết luận **được chứng minh**
nhờ §G.2, không phải lời khai.

---

## 7 · Đối chiếu với đặc tả

In tự động mỗi lần `make run`:

| Đại lượng | Đặc tả | Đo được |
|---|---|---|
| `t_seal` | 1,28 giờ | 1,26 giờ |
| Sàn kẻ gian | 38,4 phút | 37,9 phút |
| Biên dựng lại (0,005 $/giờ) | 1.600× | 1.581× |
| Biên dựng lại (0,04 $/giờ) | 12.800× | 12.647× |
| Gian 1.000 hợp đồng | 53,3 nhân | 52,7 nhân |

Lệch dưới 2 %. Cộng 13 phép đối chiếu mã ↔ đặc tả trong
`common/tests/test_spec_consistency.py`.

---

## 8 · Chưa đo được

Phải viết vào phần Giới hạn, đừng để trống:

| Đại lượng | Vì sao | Xử lý trong bài |
|---|---|---|
| `t_worker`, `t_agg` | cần SP1, máy 37 GiB không đủ | ước lượng từ 192 × 10⁹ chu kỳ/ô, ghi rõ là ước lượng |
| `c_sha` | cần SP1 | quét 3 giá trị → phân tích độ nhạy |
| `t_prove` | cần chạy `bundle_gen` | chưa chạy |
| Phí DA thật | cần Celestia Mocha | lý thuyết 0,00024 $/blob |
| **Trường `signer` do Celestia áp đặt** | cần Mocha | **giới hạn nặng nhất còn lại** |
| SP1 sound | ngoài phạm vi | mô hình chi phí, ghi rõ |
