# Runbook cho server — cài toolchain và chạy đo

Viết sau khi **cài và chạy được thật** trong một môi trường bị chặn mạng khá
gắt. Mọi lệnh dưới đây đã chạy qua, trừ hai chỗ ghi rõ là chưa.

README cũ của `sp1_verify/` nói *"không chạy được SP1 trong môi trường sandbox vì
`sp1up` bị chặn mạng và toolchain riscv tùy biến không cài được"*. **Câu đó nay
sai** — cài được, bằng cách đi vòng qua GitHub releases. Cách làm ở mục 2.

---

## 1. Ba tầng công cụ, và tầng nào cần cho việc gì

| Việc | Cần gì | Đã chạy được chưa |
|---|---|---|
| Test Python, E2E trong tiến trình | chỉ Python 3.12 | **rồi**, 100 test pass |
| Hợp đồng | `solc` 0.8.24, Foundry | biên dịch **rồi**; `forge test` **chưa** |
| Mạch Nova/Spartan (L1) | Rust ≥ 1.85 | **rồi**, chạy ra bằng chứng 13.776 byte |
| Đếm chu kỳ SP1 (L3) | toolchain riscv của SP1 | guest **build rồi**; host **chưa build** |
| DA Celestia thật | Docker | **chưa** |

---

## 2. Cài Rust và toolchain SP1

### 2.1 Rust thường, cho mạch Nova/Spartan

Cây phụ thuộc có crate dùng `edition2024`, nên **Rust 1.75 mặc định của Ubuntu
24.04 KHÔNG đủ**. Lỗi sẽ là:

```
feature `edition2024` is required ... not stabilized in this version of Cargo
```

Cách qua:

```bash
apt-get install -y rustc-1.89 cargo-1.89
export PATH=/usr/lib/rust-1.89/bin:$PATH
cargo --version          # phải ra 1.89.x
```

Nếu gặp `lock file version 4 requires -Znext-lockfile-bump` thì đó là dấu hiệu
cargo cũ đang chạy, không phải lock hỏng.

### 2.2 Toolchain SP1, cho phần đếm chu kỳ

Đường chính thức là `curl -L https://sp1.succinct.xyz | bash` rồi `sp1up`. Nếu
máy chặn miền đó, đi vòng như sau — **đây là phần đã kiểm**.

**Bước 1 — lấy `cargo-prove`.** Tên asset phải đúng, sai một chữ là 404:

```bash
mkdir -p ~/.sp1/bin && cd /tmp
curl -sSL -o cp.tar.gz \
  https://github.com/succinctlabs/sp1/releases/download/v6.3.1/cargo_prove_v6.3.1_linux_amd64.tar.gz
tar -xzf cp.tar.gz -C ~/.sp1/bin
~/.sp1/bin/cargo-prove prove --version
```

**Bước 2 — KHÔNG chạy `install-toolchain`.** Lệnh đó đòi `rustup`:

```
Error: Rust is not installed. Please install Rust from https://rustup.rs/
```

Tải thẳng toolchain thay vì để nó tự tải. 368 MB:

```bash
mkdir -p ~/.sp1/toolchains/succinct && cd ~/.sp1/toolchains/succinct
curl -L -o /tmp/sp1rust.tar.gz \
  https://github.com/succinctlabs/rust/releases/latest/download/rust-toolchain-x86_64-unknown-linux-gnu.tar.gz
tar -xzf /tmp/sp1rust.tar.gz --strip-components=1
./bin/rustc --print target-list | grep succinct
# phải thấy: riscv32im-succinct-zkvm-elf và riscv64im-succinct-zkvm-elf
```

**Bước 3 — ghép hai nửa.** Toolchain SP1 **chỉ có `rustc`, không có `cargo`**.
Dùng `cargo` 1.89, đặt `rustc` của SP1 đứng trước trong `PATH`:

```bash
export PATH=$HOME/.sp1/toolchains/succinct/bin:$HOME/.sp1/bin:/usr/lib/rust-1.89/bin:$PATH
```

**Bước 4 — build guest bằng `cargo-prove`, KHÔNG bằng `cargo build` trần.**

`cargo build --target riscv32im-succinct-zkvm-elf` sẽ chết ở `getrandom`:

```
error: could not compile `getrandom` (lib) due to 4 previous errors
```

Vì thiếu cờ mà `cargo-prove` tự đặt: `--cfg getrandom_backend="custom"`,
`-C passes=lower-atomic`, `-C link-arg=--image-base=...`, mấy `-C llvm-args`.
Nên phải:

```bash
cd sp1_verify/guest
cargo-prove prove build
```

Kết quả đã kiểm:

```
Finished `release` profile [optimized] target(s) in 1m 16s
SP1_ELF_engram-guest=.../elf-compilation/riscv64im-succinct-zkvm-elf/release/engram-guest
```

---

## 3. Đo `f` và `m` — mục tiêu chính

Hai hằng số này hiện nằm trong `common/src/engram_common/constants.py` dưới nhãn
`[ĐO]` nhưng **nguồn ở repo khác**:

```python
ZKVM_FIXED_COST_F = 45.385e9      # nạp + tiền xử lý vk 4.738.776 byte
ZKVM_MARGINAL_COST_M = 11.255e9   # verify MỘT bằng chứng Spartan trong guest
```

Nguồn gốc: hồi quy trên **ba** điểm N = 1, 2, 3.

### Cần chạy gì

```bash
# 1. build host (chưa kiểm ở đây — xem cảnh báo dưới)
cd sp1_verify/host && cargo build --release

# 2. sinh bundle đầu vào
cd ../bundle_gen && cargo run --release -- <tham số>

# 3. quét N rồi hồi quy
cd .. && ./sweep.sh          # hoặc ./run_execute_today.sh
python3 analyze.py
```

`sweep.sh` có sẵn bốn tính chất đáng dùng, ghi trong đầu file: preflight kiểm
quyền ghi và toolchain trước; smoke test 5 phút trước khi đốt 3 giờ; chạy
**execute** trước vì rẻ, prove sau; và `SKIP_DONE=1` để chạy lại không mất công.

### Cảnh báo: host CHƯA build được ở đây

`host/Cargo.toml` dùng `sp1-sdk 6.3.1`, và chú thích trong đó ghi rõ nó **cố ý
không** import `prover` vì **xung đột `generic-array`** giữa `nova-snark` và
`sp1-sdk`. Anh chưa build được bước này, nên đây là chỗ đầu tiên có thể vỡ trên
máy em.

Nếu vỡ vì `generic-array`, hướng xử lý là giữ nguyên ranh giới: host chỉ đọc
`ProofBundle` từ file do `bundle_gen` sinh, không link chung crate với nova.

### Quét bao nhiêu điểm

Ba điểm là ít, và thầy đã yêu cầu phân biệt measured / modelled / **extrapolated**.
Server 37 GiB thì quét được nhiều hơn. Đề nghị:

```
N = 1, 2, 4, 8, 16, 32
```

Sáu điểm execute, mỗi điểm là đếm chu kỳ thật. Khi đó câu trong bài đổi từ *"hồi
quy trên ba điểm"* thành *"hồi quy trên sáu điểm, R² = …, phần ngoại suy còn lại
là từ 32 tới 10.000"*. Đó là cải thiện đúng hướng thầy yêu cầu.

### Một limitation phải giữ

`guest/src/nmt.rs`, 454 dòng, **chưa nối vào luồng**. Chú thích đầu `main.rs` tự
ghi: file đó từng nằm im trong repo không được biên dịch lần nào, nay gate sau
feature. Kiểm nó biên dịch được:

```bash
cd sp1_verify/guest && cargo check --features nmt
```

Nghĩa là **phần phủ đầy đủ của Celestia chưa chạy trong guest**, và số chu kỳ đo
được **chưa gồm nó**. Khi nối thật, nhớ thêm patch `sha2` của SP1 để dùng
precompile SHA-256 — không có nó thì lập luận "NMT rẻ" ở đầu `nmt.rs` không còn
đúng.

---

## 4. Mạch Nova/Spartan — đã chạy, số đo ở đây

```bash
export PATH=/usr/lib/rust-1.89/bin:$PATH
cd circuit && cargo build --release -p prover --bin engram_prove
cd circuit && cargo build --release -p prover --bin engram_verify
cd .. && make e2e-real
```

Đo được trên máy **1 vCPU, 3 GB RAM**, sector 16 chunk × 4 KiB, 3 thách thức:

| Bước | Đo được |
|---|---|
| Niêm phong 64 KiB | 57,3 ms |
| Nova `PublicParams::setup` | 41.719,6 ms |
| Fold 3 bước + nén Spartan | 96.088,9 ms |
| Bằng chứng nén | **13.776 byte** |
| Xác minh | 772,2 ms |
| `vk.bin` | **4.738.776 byte** |

Hai số in đậm xác nhận `BUNDLE_SIZE_BYTES` và con số trong docstring của
`ZKVM_FIXED_COST_F`. **Thời gian thì đừng dùng** — máy một nhân, cận trên xấu.
Chạy lại trên server 37 GiB.

Khi đo lại, nhớ tách hai thứ: `seal()` **không song song hoá được** theo thiết
kế nên thêm nhân không rút ngắn niêm phong một sector; nén Spartan thì có. Gộp
hai cái sẽ ra kết luận sai về khả năng mở rộng theo nhân.

---

## 5. Fan-in trong mạch — CHƯA làm, và vì sao

Em có nhắn "nếu sửa được mạch mà đo không mất thời gian thì sửa luôn". Anh
**không làm**, và đây là lý do, không phải lười.

Mạch hiện tại, `circuit/prover/src/proving.rs` phần 5b, tái tính `D_ji` trong
mạch từ 133 limb của chunk thô rồi ra `R_ji` từ `D_ji` và `S_prev`. Thêm fan-in
đòi:

- witness thêm **5 trạng thái `S`** ở các vị trí fan-in
- và **5 đường Merkle nữa** để buộc 5 giá trị đó vào `sealed_root` — nếu không,
  prover tự bịa chúng
- tức khoảng **6 lần** số phép băm Merkle trong mạch

Nén Spartan đã tốn 96 giây cho mạch hiện tại trên 1 nhân. Anh **không đoán được**
nó thành bao nhiêu, và không đo nhanh được ở đây. Ship một mạch sửa mà chưa
verify được là đúng loại rủi ro em đã bảo tránh.

**Hệ quả phải ghi vào bài:** `circuit/prover/src/sealing.rs` hiện thực Thuật toán
1c không fan-in; SeqWide có fan-in nằm ở `provider/src/provider/sealing.py` và là
**thiết kế + mô phỏng**. Mọi số liệu L1 đo được là số của 1c.

Nếu trên server em muốn thử, thứ tự an toàn là: sửa mạch → chạy `engram_prove`
với sector nhỏ nhất → so thời gian nén Spartan với 96 giây → rồi mới quyết.

---

## 6. Thứ tự chạy đề nghị trên server

| # | Việc | Vì sao thứ tự này |
|---|---|---|
| 1 | `cd chain && forge test` | Toàn bộ logic Solidity của bốn vòng vá **chưa chạy lần nào** |
| 2 | `forge test --match-contract Baselines` + `make gas` | Table 1, Table 2, Fig. 3 phải đo lại vì hợp đồng đã đổi |
| 3 | `make circuit-build && make e2e-real` | Lấy số proving thật trên phần cứng của em |
| 4 | `cd sp1_verify/host && cargo build --release` | Chỗ dễ vỡ nhất, biết sớm |
| 5 | `./sweep.sh` với N = 1,2,4,8,16,32 | Ra `f` và `m` đo tại chỗ |
| 6 | `make celestia-up && make e2e-real-celestia` | Xác minh trường signer trên Celestia thật |

Bước 1 quan trọng nhất: biên dịch sạch chỉ nói kiểu đúng, không nói logic đúng.
