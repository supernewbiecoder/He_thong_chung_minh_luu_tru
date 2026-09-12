# Ba bản vá trong vòng này

Áp dụng lên `He_thong_chung_minh_luu_tru`. Toàn bộ 58 test Python pass.

## 1. D1 — `claimSettlement` không buộc số tiền vào lá (nghiêm trọng nhất)

**Lỗi.** Hàm nhận `leafDigest` đã băm sẵn cùng `beneficiary`, `rewardWei`,
`slashWei` làm tham số rời, rồi chỉ kiểm digest có nằm trong cây Merkle. Phép
kiểm đó chứng minh "digest này có trong cây", KHÔNG chứng minh "digest này ứng
với số tiền vừa truyền vào". Danh sách quyết toán công bố trên DA nên ai cũng
dựng được một cặp (digest, đường Merkle) hợp lệ, rồi điền ví mình và số tiền
bằng cả số dư hợp đồng.

**Vá.** Nhận các trường của lá, tự băm lại bằng `_leafDigest`, rồi mới leo cây.
Bỏ tham số `beneficiary`: tiền đi tới địa chỉ `provider` ghi TRONG lá.

**Kèm theo.** Thêm `epoch` vào ảnh trước. Không có nó, hai epoch sinh lá giống
hệt nhau sẽ cho cùng digest, mà `settlementClaimed` đánh dấu theo digest, nên lá
thứ hai vĩnh viễn không rút được.

**Đồng bộ mã hoá.** `SettlementLeaf.digest()` đổi từ little-endian sang
big-endian cho khớp `abi.encodePacked`, và thêm nhãn miền `ENGRAM_LEAF_V1`.

## 2. D2 — cây Merkle không tách miền lá với nút trong

**Lỗi.** Nút trong và lá đều chỉ là 32 byte băm, nên trình một nút trong ra như
thể nó là lá, kèm đường Merkle ngắn hơn, vẫn khớp gốc.

**Vá.** Nút trong mang tiền tố `0x01` ở cả `_merkleRoot` (Solidity) và
`crypto._node` (Python). Lá mang nhãn `ENGRAM_LEAF_V1`, nên hai dạng ảnh trước
không bao giờ trùng.

**Còn một điểm cố ý giữ.** Số lá lẻ vẫn nhân đôi lá cuối. Điều vô hiệu hoá nó là
`num_verified` trong public values được hợp đồng đối chiếu với
`expectedDealCount`: danh sách giả luôn lệch số lá nên bị bắt ở mắt xích ④.

## 3. Hoa hồng phạt dưới nghẽn DA

**Lỗi.** Hoa hồng 5 % giả định lá phạt phản ánh gian lận thật. Dưới nghẽn DA,
nút trung thực không đăng được bằng chứng và bị phạt hàng loạt, nên kẻ gây nghẽn
tự nộp lá phạt và THU hoa hồng. Khoản thu tăng theo N, nên bất đẳng thức "chi phí
tấn công > giá trị thu được" hỏng đúng lúc mạng lớn lên.

**Vá.** Guest xuất thêm một byte `window_saturation` ∈ [0,255], tỉ lệ block
trong cửa sổ có square đạt cỡ tối đa. Hợp đồng treo hoa hồng khi vượt ngưỡng 179.
M��c phạt KHÔNG đổi — hạ mức phạt là sai chỗ, vì nó còn phải chặn nút xoá dữ liệu,
và hoa hồng là tỉ lệ của nó nên hạ phạt không đổi hình dạng bài toán.

**Vì sao bằng cớ này khách quan.** Nút không tự tạo ra được: muốn dựng lên phải
thật sự trả tiền lấp đầy block Celestia. Và nó gần như miễn phí, vì guest đã phải
nạp gốc hàng cột của từng block để dựng `data_root`, nên nó đã biết kích thước
square.

## Ảnh hưởng tới số liệu trong bài

| Hạng mục | Đổi không |
|---|---|
| Calldata 868 byte | **Không.** Đệm ABI làm tròn 297 lên 320 y như 296 |
| Phí giao dịch cơ bản 34.888 | **Không** |
| Gas `commitEpoch` (474.260) | Thêm một `calldataload` và một phép gán; ước lượng < 200 gas, **phải đo lại bằng `forge`** |
| Số khe lưu của `EpochRecord` | **Không.** 1+4+20+1 = 26 byte, vẫn một khe |
| Gas `claimSettlement` | Tăng, do băm lại lá và calldata dài hơn. Hàm này KHÔNG xuất hiện trong Table 1, Table 2 hay Figure 3 |
| Table 1, Table 2, Figure 3, Abstract | **Không**, trừ con số gas logic hợp đồng sau khi đo lại |

## Phải sửa trong bài

1. Mọi chỗ "296 B public values" → 297. Gồm Fig. 1 và Implementation.
2. Sửa luôn lỗi calldata: bài ghi 844 B nhưng 21.000 + 844×16 = 34.504 ≠ 34.888.
   Con số đúng là **868 B**, và tỉ lệ giảm dữ liệu ở batch 1.000 là 15.871× chứ
   không phải 16.322×.
3. Thêm hai ba câu vào Design hoặc Discussion về việc treo hoa hồng khi nghẽn.
4. Chạy `forge test --gas-report`, cập nhật gas logic hợp đồng.

## Việc còn lại chưa vá

Xem `DANH_MUC_SUA_SoICT_zkVM.md`. Nặng nhất trong số còn lại:

- D3 `voidEpoch` không kiểm quyền gọi, ai cũng void được epoch với ~30.000 gas
- D4 `abortDeal` nhận `currentDeadline` từ người gọi, `openedAtDeadline` không
  bao giờ được gán
- D5 `openDeal` không kiểm bốn trường quyết định vị trí
- D6 `activeDealCount` chỉ tăng, nhánh giảm là code chết
- D7 aggregator nhận `expected_cells` từ host
- D8 `slashWei` không trừ cọc của ai cả

## Test

Python, 58 pass:

```
python3 -m pytest common/tests worker/tests aggregator/tests -q
```

M��i thêm:
- `common/tests/test_settlement_binding.py` — D1, D2
- `common/tests/test_window_saturation.py` — hoa hồng dưới nghẽn

Solidity, **chưa chạy được trong môi trường soạn bản vá này**:
- `chain/test/ClaimSettlement.t.sol`
- `chain/test/BountyUnderCongestion.t.sol`

Hai file trên có khung và các phép khẳng định thuần tuý chạy được ngay; phần cần
dựng epoch Final đang để `vm.skip(true)` và cần nối vào fixture sẵn có trong
`EngramManager.t.sol`. Chạy `forge test` rồi bỏ `vm.skip`.

---

# Vòng 2: các mục trong góp ý của thầy có phần CODE

Ba bản vá trên là lỗi code anh tự tìm ra. Phần dưới là phần **code** của những
mục thầy nêu. Phần chữ trong bài vẫn phải sửa riêng.

## P0.3 — mắt xích thứ tư (mục nặng nhất)

Thầy nêu ba điều kiện. Bản trước chỉ có một.

### ① Mỗi ChildProof phải bind với `snapshot_id` — TRƯỚC ĐÂY THIẾU

`ShardResult` không mang `snapshot_id`, và `reconcile_shard_results` chỉ đối
chiếu `expected_count` giữa hai bản của **cùng một ô**.

Hai điểm yếu của cách đó:

- Trong cùng một ô: bằng nhau về **số lượng** không có nghĩa là cùng một sổ.
  Hai sổ khác nhau vẫn cho ra cùng |E_cell|.
- Giữa các ô khác nhau: **không có phép kiểm nào**. Ô 1 dựng từ sổ epoch trước,
  ô 2 từ sổ epoch này, Σ|E_cell| vẫn khớp `expectedDealCount`.

**Vá.** `ShardResult.snapshot_id`, reconcile đòi mọi ChildProof mang cùng một
giá trị (lỗi mới `SnapshotMismatch`), và `aggregate_epoch` đối chiếu giá trị
chung đó với `snapshot_id` đi vào public values. Chuỗi khép kín:
ChildProof → evidence → public values → hằng số đóng băng on-chain.

### ② Mỗi ô kỳ vọng xuất hiện đúng một lần — CÓ, nhưng tập ô nhận từ host

`aggregate_epoch` nhận `expected_cells` làm **tham số**. Host đưa vào tập đã bớt
một ô thì `missing` rỗng, không ai báo lỗi, các hợp đồng trong ô đó lặng lẽ
không có phán quyết. Đúng lỗ mà §D.3 vá ở tầng worker, chỉ lùi lên một tầng.

**Vá.** Bỏ tham số. Dẫn xuất tại chỗ từ `epoch`, `deadlines_per_epoch`,
`n_shards` — lưới ô là tất định từ ba tham số giao thức mà hợp đồng cũng biết.

### ③ `num_verified` từ Σ|E_cell| — đã đúng từ trước, giữ nguyên

## P0.4 — guest không tự đi mạng

Code vốn đã đúng hình: `expected_from_registry(registry, onchain_snapshot_id, …)`
nhận sổ làm **đầu vào** rồi tự đối chiếu, không hề gọi mạng. Giờ `verify_shard`
nhận thẳng `snapshot_id`, nên ranh giới host/guest hiện rõ trong chữ ký hàm và
Algorithm 1 mirror được code:

```
Host input : R, registry_proof, observed_blobs
Guest      : VerifyRegistryCommitment(R, registry_proof, snapshot_id)
```

Không cần sửa logic, chỉ cần sửa câu chữ trong bài.

## P0.6 — Eq. (1) lẫn đơn vị

Bản trước so `t_prove <= W` trong khi W đếm bằng **block** còn `t_prove` đo bằng
**giây**. Thiếu đúng một hằng số: thời gian một block.

**Vá.** Thêm `CELESTIA_BLOCK_SECONDS` và `window_safety_ok()` viết đúng đơn vị:

```
t_prove <= W · t_block < t_regen + t_prove
```

Ghi chú kèm trong code: với bao đóng fan-in đo được là 23,9 % chứ không phải
100 %, `t_regen` nhỏ hơn con số trong §F.2.1, nên bất đẳng thức này **phải được
kiểm lại ở tham số hiện tại**, không mặc nhiên đúng.

## P0.9 — số hạng phụ thuộc spam bị bỏ quên trong mô hình chi phí

`prove_coverage` băm **mọi blob quan sát được** để tạo cam kết, nhưng
`merkle_root(leaves)` không nằm trong `sha256_ops`. Đúng số hạng mà spam làm
phình ra thì lại không được tính tiền.

**Vá.** `sha256_ops = ops_dataroot + ops_commit`, với `ops_commit = 2n − 1`.

Hệ quả cho bài: câu "chi phí phủ đầy đủ là nhiễu 0,006–0,12 %" **đúng khi
namespace sạch, sai khi bị spam**. Ở trần cửa sổ, số hạng này khoảng 46 lần chi
phí verify một bundle. Phải nêu điều kiện, và phải gọi bound 171 là **analytic**
chứ không phải đo được — code luôn thu phí trần, không tính ra nó.

## Chưa làm, vì cần file .tex

P0.1 citation, P0.2 gas Table 1/2, P0.5 wording Blobstream, P0.7 claim SeqWide,
P0.8 break-even, P0.10 B2, và toàn bộ P1.

Các con số đã sẵn sàng để điền:
- Table 2 cộng 34.888 vào cả ba dòng → 474.260 / 474.281 / 474.336
- B1 giao giữa N=2 và N=3; B3 giao giữa N=17 và N=18
- calldata 868 B, không phải 844; giảm dữ liệu 15.871× ở batch 1.000

## Test

67 pass. Mới thêm ở vòng 2:
- `aggregator/tests/test_snapshot_binding.py`
- `aggregator/tests/test_cell_set_derivation.py`
