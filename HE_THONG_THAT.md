# Hệ thống thật: sector trên đĩa và tầng DA có backend Celestia

Vòng này bỏ hai chỗ giả lập lớn nhất còn lại. Mục đích: giám khảo mở đúng **một
zip** là thấy được toàn bộ hệ, và phân biệt được chỗ nào chạy thật với chỗ nào
là mô hình.

---

## 1. Sector thật trên đĩa, bỏ sector ảo

### Trước

`storage.py` **sinh** nội dung chunk theo yêu cầu từ một hạt giống, và mô phỏng
mất dữ liệu bằng một **tập chỉ số** trong bộ nhớ:

```python
def chunk(self, index):
    if index in self.lost_indices:
        return b"\x00" * CHUNK_SIZE_BYTES     # trả rác
    return generate_chunk(self.deal_id, index)
```

Cách đó cho `piece_root`, `sealed_root`, chỉ số thách thức và đường Merkle đều
thật, mà tốn gần 0 dung lượng. Nhưng nó đánh mất đúng thứ cả hệ tồn tại để
kiểm: **không có byte nào để xoá**. Mọi kết luận kiểu "nút gian bị bắt" là kết
luận về một cờ trong RAM, không phải về đĩa.

### Sau

`provider/sector.py` — sector nằm trên đĩa, truy cập theo offset cố định:

| Việc | Gọi gì | Xảy ra gì trên đĩa |
|---|---|---|
| Ghi | `Sector.create(root, deal_id, n)` | tạo `<deal_id>.sector`, `n × 4096` byte |
| Ghi từ dữ liệu khách | `Sector.from_bytes(root, deal_id, data)` | ghi thật, đệm 0 chunk cuối |
| Đọc | `sector.chunk(i)` | một phép `seek` tới `i·4096` |
| Niêm phong | `sector.iter_chunks()` | đọc theo **luồng**, không nạp cả sector vào RAM |
| Mất một phần | `sector.lose_fraction(f)` | **ghi đè 0 thật** lên các chunk đó |
| Xoá sạch | `sector.delete()` | gỡ file |

Hai điểm đáng chú ý:

**Xoá rồi thì `chunk()` ném `ChunkMissing`, không trả rác.** Một nút đã xoá thật
thì **không có gì** để đưa vào mạch, nên ràng buộc không dựng được. Trả rác mô
tả sai tình huống — đó là nút *còn* dữ liệu nhưng dữ liệu hỏng.

**`on_disk_bytes` là số đo, không phải cờ.** Sau `delete()` nó bằng 0, và mọi
đường đọc đều thấy, kể cả đường không biết gì về mô phỏng.

### Kiểm được điều gì mà trước đây không

`provider/tests/test_sector_that.py`, bài quan trọng nhất:

```python
def test_mat_du_lieu_LAM_DOI_vet_niem_phong(root):
    st = DealStorage.create(root, DEAL, 8)
    truoc = seal(list(st.iter_chunks()), RID).sealed_root
    st.lose_fraction(0.5)
    sau = seal(list(st.iter_chunks()), RID).sealed_root
    assert sau != truoc
```

Vết niêm phong đổi vì **byte đổi**, không phải vì một cờ được bật.

### Đánh đổi, phải nói trước khi chạy

Sector thật của giao thức là 8.388.608 chunk = **32 GiB**. Hai mươi hợp đồng là
640 GiB. Không máy nào trong vòng thí nghiệm chạy nổi.

Nên `n_chunks` là **tham số của `SimNetwork`**, không phải hằng số giấu trong
mã, và giá trị dùng được in ra cùng kết quả. Chạy với 8 chunk hay 8 triệu chunk
là lựa chọn của người chạy; không có gì bị ẩn đi.

---

## 2. Tầng DA: một giao diện, hai backend

`common/engram_common/da.py`.

```
ENGRAM_DA=memory     trong tiến trình, không cần mạng   ← mặc định, dùng cho CI
ENGRAM_DA=celestia   JSON-RPC tới celestia-node         ← devnet hoặc Mocha
```

Cùng một đoạn mã worker chạy trên cả hai.

### Vì sao phải có cả hai

`MemoryDA` một mình thì mọi kết luận chỉ nói về một danh sách trong RAM. Ba thứ
mà thiết kế dựa vào đều **thuộc về Celestia**, không thuộc về Engram, và chỉ
backend thật mới kiểm được:

1. Trường `signer` của share phiên bản 1 có thật sự được đồng thuận áp đặt không
2. Namespace có thật sự mở cho mọi người ghi không
3. Một blob có thật sự lên được block trong cửa sổ `W` không

`CelestiaDA` một mình thì không chạy được trong CI, và mỗi lần chạy test phải
dựng devnet.

### Share phiên bản 1, không phải 0

`CelestiaDA.submit` dùng `share_version = 1` và điền `signer`. Không phải lựa
chọn thẩm mỹ: **toàn bộ phòng thủ chống mạo danh blob dựa vào trường đó**. Với
share version 0, blob không mang signer, worker không phân biệt được ai đăng, và
bộ lọc F3b vô nghĩa.

Nguồn gốc để cite trong bài: CIP-21 *"Introduce blob type with verified signer"*,
nằm trong bản nâng cấp **Ginger tức celestia-app v3** — kích hoạt Arabica
5/11/2024, Mocha tháng 11/2024, Mainnet Beta tháng 12/2024. Không phải tính năng
thử nghiệm.

### Một chỗ dễ hiểu nhầm, ghi rõ trong mã

Trường signer cho **attribution**, không cho **admission control**.

Kẻ ngoài **vẫn đăng được** blob vào namespace của mình — namespace không có chủ
và Celestia không có cơ chế khoá ghi. Thứ nó không làm được là điền `signer`
thành địa chỉ của người khác.

Nên rác vẫn vào block và worker vẫn phải tải; cái rẻ đi là việc **loại** nó, chỉ
tốn một phép so sánh 20 byte. `MemoryDA.read` vì thế trả về **mọi** thứ ai đó đã
ghi, kể cả rác. Đó là hành vi đúng, không phải thiếu sót — và có test chốt:

```python
def test_namespace_mo_ai_cung_ghi_duoc():
    da.submit(NS, HDR, b"that", b"\x01" * 20)
    da.submit(NS, HDR, b"rac",  b"\xbb" * 20)   # kẻ lạ, chữ ký của chính nó
    assert len(da.read(NS, da.height, da.height + 1)) == 2
```

### Cổng chặn mạng chính

Một lần chạy thử không được phép tiêu TIA thật. `_guard_submit` chặn cứng, và
chỉ hai cách mở, chọn đúng một:

```
CELESTIA_LOCAL_DEVNET=1   node loopback trên chính máy này
CELESTIA_NETWORK=mocha    testnet công khai, TIA lấy từ faucet
```

`CELESTIA_NETWORK=mainnet` thì ném lỗi, không có ngoại lệ nào. Có test.

### Dựng devnet

`deploy/docker-compose.celestia-devnet.yml`, gồm celestia-app `v6.4.4-mocha` và
celestia-node `v0.28.5-mocha`.

```
make celestia-up        # dựng validator + bridge
make celestia-status    # kiểm đã sẵn sàng chưa
make run-celestia       # chạy mô phỏng với DA THẬT
make celestia-down      # dừng và dọn
```

Cổng ánh xạ ra `46657` và `46658` chứ không phải `26657/26658` mặc định, vì máy
chạy thí nghiệm dùng chung với hạ tầng Celestia khác. Chi tiết trong chú thích
đầu file compose.

### `square_roots` — đầu vào cho tín hiệu nghẽn DA

Cả hai backend có `square_roots(heights)`. Ở `CelestiaDA` nó đọc thật từ `dah`
của header block:

```python
out.append(len(dah.get("row_roots", [])) + len(dah.get("column_roots", [])))
```

Đây là đại lượng mà `prove_coverage` dùng để đo độ lấp đầy cửa sổ, và là bằng cớ
**khách quan** về nghẽn DA: nút không tự dựng lên được, muốn dựng phải thật sự
trả tiền lấp đầy block Celestia.

---

## 3. Mạch THẬT: Nova + Spartan trên BN254

Workspace Rust nằm ở `circuit/`, gồm `core_primitives`, `prover`, `verifier`,
`data_generator`. Hai binary là cầu sang tầng Python:

    engram_prove    niêm phong sector → Nova fold → nén Spartan → ghi proof.bin
    engram_verify   đọc proof.bin + vk.bin + z0.bin → verify

### Số đo THẬT, chạy trên máy soạn bản vá này

Máy: **1 vCPU, 3 GB RAM**. Sector 16 chunk × 4 KiB, 3 thách thức.

| Bước | Đo được |
|---|---|
| Niêm phong 64 KiB | **57,3 ms** |
| Nova `PublicParams::setup` | **41.719,6 ms** |
| Fold 3 bước + nén Spartan | **96.088,9 ms** |
| **Kích thước bằng chứng nén** | **13.776 byte** |
| Xác minh | **772,2 ms** |
| Khoá xác minh `vk.bin` | **4.738.776 byte** |

Hai con số cuối đáng chú ý: **13.776 byte đúng bằng `BUNDLE_SIZE_BYTES`**, và
**4.738.776 byte đúng bằng con số trong docstring của `ZKVM_FIXED_COST_F`**. Hai
hằng số đó nay có nguồn đo nằm ngay trong repo, chạy lại được bằng một lệnh.

Thời gian thì là cận trên xấu vì máy chỉ có một nhân. Chạy trên máy nhiều nhân
sẽ khác, và đó là lý do mọi số thời gian phải đo lại trên phần cứng của người
nộp chứ không chép từ đây.

### Thuật toán niêm phong: HAI bản trong repo, cố ý

| | `circuit/prover/src/sealing.rs` | `provider/src/provider/sealing.py` |
|---|---|---|
| Công thức | `R_i = H4(D_i, S_{i-1}, i, replica_id)` | gieo từ `S_prev` + fan-in φ=6, rồi hấp thụ chunk vào trạng thái |
| Fan-in | **không** | có |
| Trạng thái | **trong mạch, chạy thật** | thiết kế + mô phỏng |

Đưa fan-in vào mạch đòi witness thêm 5 trạng thái và **5 đường Merkle nữa** để
buộc chúng vào `sealed_root`, tức khoảng 6 lần số phép băm Merkle trong mạch.
Đó là một lần sửa mạch thật chứ không phải vá nhỏ, và chưa làm.

**Hệ quả cho bài:** Section 4 phải nói rõ SeqWide là **thiết kế và mô phỏng**,
chưa vào mạch. Mọi số liệu L1 đo được là số của Thuật toán 1c.

### Chuỗi đầu-cuối thật

`make e2e-real` chạy sáu bước, và in ra cái gì thật cái gì mock:

```
① sector trên đĩa      65.536 byte
② niêm phong + Nova + Spartan     bằng chứng 13.776 byte
③ đăng lên DA          namespace theo mảnh
④ worker đọc TỪ DA rồi verify     PASS, 772 ms
⑤ đục lỗ 4 chunk THẬT → sealed_root đổi → verify FAIL
⑥ SP1 wrap + Groth16 + EVM        MOCK
```

Bước ④ verify **byte đọc về từ DA**, không phải byte trên đĩa của nút — đó mới
là đường đi thật. Bước ⑤ là chỗ chứng minh hệ bắt được nút mất dữ liệu bằng
**mật mã**, không phải bằng một cờ.

---

## 4. Còn lại gì là mô hình, nói thẳng

Sau vòng này, ba thứ vẫn là mô hình chứ không phải chạy thật. Bài **phải** nói
ra, và mã đã đánh dấu.

| Thứ | Trạng thái | Đánh dấu ở đâu |
|---|---|---|
| Hàm băm trong **tầng Python** | `poseidon2_stub` dùng BLAKE2b. Mạch Rust thì dùng **Poseidon2 thật** — hai tầng khác nhau, xem `circuit/core_primitives/src/poseidon2.rs` | `[CHỐT D3]` trong `crypto.py` |
| Bằng chứng **Groth16** | Vẫn là đối tượng giả đúng kích thước. Bằng chứng **Spartan** thì nay là thật, xem mục 3 | `[CHỐT D3]` trong `constants.py` |
| Gói SP1 | **Mock.** SP1 chỉ execute được; prove hết bộ nhớ ở 35 GB | `HE_THONG_THAT.md` mục 3 |
| Chi phí zkVM `f` và `m` | Hồi quy trên **ba điểm đo** N = 1, 2, 3, rồi ngoại suy | `[ĐO]` trong `constants.py` |

Ba dòng trên là ranh giới giữa "chạy thật" và "mô hình". Sau khi có sector thật
và DA thật, ranh giới đó **hẹp hơn hẳn** so với trước: dữ liệu thật, đĩa thật,
mạng thật, chỉ còn phần mật mã trong mạch là mô hình.

---

## 4. Trạng thái kiểm chứng

| Việc | Kết quả |
|---|---|
| Test Python | **100 pass** |
| E2E hai epoch với sector thật + mất dữ liệu thật | **thông**, nút bị đục lỗ ra FAIL |
| Tầng DA, backend bộ nhớ | có test, gồm cả cổng chặn mạng chính |
| Tầng DA, backend Celestia | **chưa chạy ở đây** — môi trường soạn bản vá không có Docker và không ra được mạng Celestia |
| Biên dịch hợp đồng, solc 0.8.24 | sạch |
| `forge test` | **chưa chạy** |

Hai dòng cuối là giới hạn thật, không phải cách nói khiêm tốn. Backend Celestia
đã viết đủ và đối chiếu tên method với Node API v0.28.x, nhưng **chưa có một lần
gọi thật nào** từ môi trường này. Việc đầu tiên nên làm trên máy của em là:

```
make celestia-up && make celestia-status && make run-celestia
```

Nếu tên method lệch vì node khác version thì sửa **một chỗ duy nhất** là lớp
`CelestiaDA`, vì mọi nơi khác gọi qua nó.
