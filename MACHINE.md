# MACHINE.md — môi trường đo

Mọi con số **thời gian** trong bài phụ thuộc máy này. Không có tệp này thì các
số đó không tái lập được, và người đọc không biết nên tin chúng tới đâu.

Số **gas** thì không phụ thuộc máy — EVM là tất định — nhưng phụ thuộc phiên bản
`solc` và số vòng tối ưu, nên vẫn ghi ở đây.

Đo ngày **13–14/9/2026**.

---

## 1. Phần cứng

| | |
|---|---|
| CPU | Intel Xeon E-2276G @ 3,80 GHz (tối đa 4,90 GHz) |
| Nhân / luồng | **6 nhân vật lý, 12 luồng**, một socket |
| RAM | **62 GiB tổng** — nhưng chỉ ~36 GiB khả dụng lúc đo, 24 GiB đang bị tiến trình khác giữ |
| Đĩa | NVMe SSD, Intel SSDPE2KX010T8, 931,5 GB (`ROTA=0`) |
| Hệ điều hành | Ubuntu, kernel 6.8.0-111-generic |
| Máy dùng chung | **có** — devnet Celestia của người khác chạy suốt 3 tuần |

### Hai điều phải nói rõ về cấu hình này

**① Con số "37 GiB" dùng trong các ghi chú trước là SAI.** Máy có **62 GiB
tổng**; 37 GiB là phần *khả dụng* tại một thời điểm, vì khoảng 24 GiB đang bị
tiến trình khác giữ. Hệ quả cho bài: câu *"Groth16 wrapping hết bộ nhớ ở 35 GB"*
mô tả một lần thử trên máy **chỉ còn ~36 GiB trống**, không phải trên một máy 62
GiB rảnh. Đây là giới hạn của **lần thử**, không phải một trần tuyệt đối đã được
xác lập. Bài nên viết đúng như vậy, hoặc thử lại khi máy rảnh.

**② "Toàn nhân" nghĩa là 12 luồng trên 6 nhân vật lý.** `taskset -c 0-3` cấp 4
luồng. Trên bố trí CPU thông thường của Linux, CPU 0–5 là sáu nhân vật lý và 6–11
là siblings, nên `0-3` nhiều khả năng là **4 nhân vật lý riêng biệt** chứ không
phải 2 nhân với siblings. Kiểm bằng:

```bash
cat /sys/devices/system/cpu/cpu0/topology/thread_siblings_list
```

Nếu ra `0,6` thì suy đoán trên đúng. Điều này ảnh hưởng cách diễn giải mức chậm
đi: so 4 nhân vật lý với 6 nhân vật lý là một tỉ lệ, so 4 luồng với 12 luồng là
một tỉ lệ khác.

> **Cảnh báo về nhiễu.** Máy dùng chung, và trong lúc đo có lúc chạy song song
> `sweep.sh` với các việc khác. Các lần chạy dùng cho bài nên được thực hiện khi
> máy rảnh; nếu không chắc thì ghi rõ ở dòng tương ứng trong `e2e_real.csv`.

---

## 2. Bộ công cụ

| Công cụ | Phiên bản | Dùng cho |
|---|---|---|
| Foundry `forge` | **1.8.1** | toàn bộ số gas |
| `solc` | **0.8.24**, 200 vòng tối ưu | biên dịch hợp đồng |
| `cargo` | **1.95.0** (`f2d3ce0bd`, 21/3/2026) | mạch Nova/Spartan |
| `rustc` | **1.95.0** (`59807616e`, 14/4/2026) | |
| `cargo-prove` | build `58c4aea`, 11/9/2026 (bản mới nhất qua `sp1up`, **không phải v6.3.1**) | build guest SP1 |
| `sp1-sdk`, `sp1-build` | **6.4.0** (cargo nâng từ 6.3.1 ghim trong Cargo.toml) | đếm chu kỳ SP1 |
| Toolchain riscv SP1 | `rust-toolchain-x86_64-unknown-linux-gnu`, bản mới nhất tại thời điểm tải | biên dịch guest |
| Python | **3.10.12** | tầng điều phối, worker, aggregator |
| `pytest` | **9.1.1** | 116 test |
| Docker | **29.1.3** (`f52814d`) | devnet Celestia |
| celestia-app | **v6.4.4-mocha** | devnet |
| celestia-node | **v0.28.5-mocha** | devnet, JSON-RPC cổng 46658 |

**Hai chỗ lệch phiên bản trong chuỗi SP1.** `cargo-prove` là bản mới nhất tải qua
`sp1up` chứ không phải v6.3.1 như tài liệu build ghi; và `sp1_verify/host/Cargo.toml` ghim `6.3.1` nhưng
cargo giải ra `6.4.0` do quy tắc tương thích semver. Build xanh và số đo dùng
được, nhưng nếu muốn tái lập chính xác thì ghim chặt:

```toml
sp1-sdk   = { version = "=6.3.1", features = ["blocking"] }
sp1-build = "=6.3.1"
```

---

## 3. Số nào phụ thuộc máy, số nào không

| Nhóm số | Phụ thuộc máy | Ghi chú |
|---|---|---|
| Gas `commitEpoch` 517.189, Table 1, Table 2 | **không** | EVM tất định; phụ thuộc `solc` và vòng tối ưu |
| Điểm giao B1, B3 | **không** | suy từ số gas |
| Calldata 868 B, public values 297 B, proof 13.776 B, vk 4.738.776 B | **không** | kích thước, không phải thời gian |
| Số chu kỳ SP1, `f` và `m` | **không** | chu kỳ RISC-V là đại lượng của chương trình |
| Thông lượng 78 Mcycles/s | **CÓ** | đây là nơi phần cứng vào |
| `seal_ms`, `setup_ms`, `prove_ms` | **CÓ** | |
| Mọi giờ trong `rq3_grid.csv` | **CÓ** | vì chúng là chu kỳ chia thông lượng |

Điểm đáng nhớ: **`f` và `m` tái lập được trên máy khác, còn số giờ suy ra từ
chúng thì không.** Ai chạy lại nên kỳ vọng cùng số chu kỳ nhưng khác số giây.

---

## 4. Các lần chạy dùng cho bài

| Phép đo | Lệnh | Trạng thái máy |
|---|---|---|
| Gas, baselines | `make gas`, `make baselines` | bất kỳ, tất định |
| `f`, `m` (4 điểm N = 1,2,4,8) | `make sp1-sweep PHASE=execute BATCH_EXECUTE="1 2 4 8"` | `ĐIỀN`: rảnh hay không |
| Đối chứng distinct (N = 5) | `make sp1-sweep PHASE=distinct DISTINCT_N=5` | `ĐIỀN` |
| Đường cong L1 (16/64/256/1024 chunk) | `for n in …; do ENGRAM_CHUNKS=$n make e2e-real; done` | `ĐIỀN` |
| Trục phần cứng (4 nhân) | `ENGRAM_CHUNKS=256 taskset -c 0-3 make e2e-real` | `ĐIỀN` |
| Celestia devnet | `make e2e-real-celestia` | devnet đã chạy sẵn 3 tuần |

Số lần lặp: **một lần mỗi cấu hình**, trừ 4 nhân ở 256 chunk chạy **ba lần**. Biên
độ giữa ba lần đó khá rộng — `fold + nén` ra 19.598, 19.767 và 22.234 ms, chênh
13 % — nên bài nên phát biểu theo **khoảng** chứ không theo một con số phần trăm
chính xác.

---

## 5. Tái lập

```bash
# 1. Test và mô phỏng — không cần gì ngoài Python
make deps && make test-py          # 116 passed
make run

# 2. Hợp đồng — cần Foundry
cd chain && forge test -vv          # 39 passed, 28 skipped
cd .. && make gas && make baselines

# 3. Mạch Nova/Spartan — cần Rust >= 1.85
make circuit-build && make e2e-real

# 4. Đếm chu kỳ SP1 — cần toolchain SP1, xem RUNBOOK_SERVER.md mục 2
make sp1-bundlegen && make sp1-sweep PHASE=execute

# 5. DA thật — cần Docker
make celestia-up && make e2e-real-celestia

# 6. Tổng hợp — chạy SAU CÙNG, đọc các hằng số vừa cập nhật
make bench-rq
```

Bước 6 phải chạy cuối, vì `bench_rq.py` đọc `COMMIT_EPOCH_GAS`,
`ZKVM_FIXED_COST_F` và `ZKVM_MARGINAL_COST_M` trong `constants.py`. Đo lại mà
không cập nhật hằng số thì bảng tổng chi phí đứng trên số cũ.

---

## 6. Cái gì KHÔNG chạy được trên máy này

| | Lý do |
|---|---|
| `make sp1-sweep PHASE=prove` | Groth16 wrapping OOM. Đã thử; nhưng lúc thử máy **chỉ còn ~36 GiB trống** trên 62 GiB tổng, nên chưa loại trừ được khả năng chạy được khi máy rảnh |
| Nghẽn DA, lỡ cửa sổ nộp, giá gas Celestia thật | devnet một validator, không ai tranh chỗ trong block |
| Phí DA đo được | `CelestiaDA.submit` chỉ trả chiều cao; chưa tra `gas_used` qua RPC cổng 46657 |
| Ranh giới HTTP giữa các dịch vụ | khung E2E nạp trong tiến trình |
| Phần phủ đầy đủ namespace trong guest | `nmt.rs` gate sau feature, chưa nối vào luồng |

Năm dòng này tương ứng với phần Limitations của bài. Ba dòng đầu là giới hạn phần
cứng hoặc hạ tầng; hai dòng cuối là việc chưa làm.
