# SP1 Verify — bộ khung verify CompressedSNARK trong zkVM

> **Luồng benchmark hiện hành:** với server chỉ còn khoảng 27 GiB RAM, dùng
> [`RUN_TODAY_27GB.md`](RUN_TODAY_27GB.md) và `run_execute_today.sh`. Mỗi điểm
> chạy trong container riêng và ghi cycles, prover gas, thời gian, throughput,
> peak RSS và cgroup peak RAM. Các lệnh thử nghiệm cũ bên dưới chỉ dùng để hiểu
> cấu trúc crate.

Verify batch bằng chứng Engram (Nova CompressedSNARK trên BN254/Grumpkin) bên trong SP1
guest, sinh Groth16 proof để EVM kiểm. Đây là **Giai đoạn 1.5 (SP1 de-risk spike)** trong
checklist — phần rủi ro nhất của dự án.

## ⚠️ Trạng thái trung thực

Mình (Claude) **không chạy được SP1 trong môi trường sandbox** vì `sp1up` bị chặn mạng và
toolchain riscv tùy biến của SP1 không cài được ở đó. Nên phần này **chưa được chạy thật** —
khác với migration BN254 / vá possession (đã chạy + kiểm chứng đầy đủ).

**Cái ĐÃ kiểm chứng trên host (target thường):**
- ✅ Type alias engine/SNARK khớp giữa host và guest (`sp1_shared`).
- ✅ Circuit stub impl `StepCircuit` với `arity()=7`, compile sạch.
- ✅ `VerifierKey`, `CompressedSNARK`, `GuestInput`, `PublicValues` đều deserialize-được.
- ✅ Phát hiện then chốt (đọc từ source nova 0.71.1): `verify()` KHÔNG gọi `synthesize()`,
  circuit type chỉ là `PhantomData<C>` → guest KHÔNG cần `core_primitives` (lazy_static/
  rayon). Đây là lý do guest nhẹ và khả thi.

**Cái BẠN phải chạy trên máy có SP1 toolchain** (xem phần "Chạy" và "Chướng ngại").

## Kiến trúc thư mục

```
sp1_verify/
├── shared/          Type CHUNG host↔guest (alias engine, ProofBundle, GuestInput, PublicValues)
├── guest/           SP1 program — build bằng `cargo prove build`
│   ├── src/main.rs        verify loop + batch_root + commit public values
│   └── engram_circuit_stub/   StepCircuit stub arity=7 (KHÔNG cần core_primitives)
└── host/            Script điều phối — build bằng cargo thường
    ├── src/main.rs        sinh ProofBundle thật từ pipeline Engram → execute/prove
    └── build.rs           tự gọi cargo prove build cho guest
```

## Luồng dữ liệu

```
pipeline Engram (prover crate)          ← đã có, đã kiểm chứng
   │ sinh CompressedSNARK thật
   ▼
ProofBundle {sealed_root, beacon, replica_id, num_steps, proof_bytes}
   │ host serialize (bincode)
   ▼
SP1 guest:
   1. deserialize vk + mỗi proof
   2. dựng z0 = [epoch,0,sector_id,sealed_root,beacon,replica_id,replica_id]
   3. proof.verify(vk, num_steps, z0)   ← TỐN CYCLES NHẤT
   4. batch_root = merkle_keccak(proof_bytes hashes)
   5. new_state_root = keccak(prev ‖ batch_root ‖ epoch)
   6. commit PublicValues
   ▼
Groth16 proof (~260B) + PublicValues → EVM contract
```

### Hai khóa phải pin độc lập

- `programVKey` được SP1 suy ra từ Guest ELF; contract truyền đúng khóa đã pin
  vào `ISP1Verifier.verifyProof`.
- `vk.bin` là verifier key của storage proof Spartan/Nova mà Host đưa vào Guest.
  Guest hiện commit `keccak256(vk_bytes)` thành `storage_vk_digest`; contract
  chỉ chấp nhận digest đã pin. Nếu thiếu bước thứ hai, Host có thể dùng Guest
  chuẩn nhưng thay storage circuit/VK bên trong.

`PublicValues` vì vậy dài 172 byte. Bố cục chính tắc nằm trong
`shared/src/lib.rs::PublicValues::{to_packed, from_packed}`.


## 🐳 Docker — một image cho execute và prove

Entry point khuyến nghị ở phía host là [`run_sp1.sh`](run_sp1.sh):

```bash
./sp1_verify/run_sp1.sh build
./sp1_verify/run_sp1.sh execute
ENABLE_PROVE=1 ./sp1_verify/run_sp1.sh prove
./sp1_verify/run_sp1.sh analyze
```

Hai chế độ dùng chung Host binary, Guest ELF, input, artifact cache và JSONL. Runner
`run_execute_today.sh` chỉ là profile tài nguyên an toàn cho server còn khoảng 27 GiB,
không phải codebase tách riêng. Xem [`RUN_UNIFIED.md`](RUN_UNIFIED.md).

## Docker — môi trường cố định (KHUYẾN NGHỊ sau các lỗi toolchain)

Docker cô lập môi trường: KHÔNG conda chen PATH, cargo/rustc đúng version, SP1 pin v6.3.1,
và tắt sẵn trim-paths (fix lỗi "remap-path-scope"). Dockerfile + docker-run.sh ở thư mục
`simulation/` (gốc, vì bundle_gen cần prover/core_primitives).

```bash
cd simulation
./docker-run.sh build      # build image, 1 lần (~10-15 phút)
./docker-run.sh gen        # sinh bundle.bin + vk.bin
./docker-run.sh execute    # ĐẾM CYCLES (tự build guest ELF trong container)
```

Trên Windows: chạy trong WSL2 với Docker Desktop bật WSL integration. Named volume giữ
cargo cache nên chỉ lần đầu lâu. Bước `./docker-run.sh prove` (Groth16) tự mount Docker socket.

Cách image xử lý 2 toolchain: PATH có cả `cargo` (host Rust 1.90, cho bundle_gen + host)
lẫn `cargo-prove` (SP1, cho guest). Chạy `cd host && cargo run` là host/build.rs tự spawn
cargo-prove build guest — không cần chạy cargo prove build tay.

---

## ⚠️ LỖI TOOLCHAIN THƯỜNG GẶP: "Unrecognized option: remap-path-scope"

Nếu `cargo run --execute` báo lỗi này khi build guest:
```
rustc 1.94.0-dev
error: Unrecognized option: 'remap-path-scope'
```
→ Nguyên nhân: `sp1up` (không pin) đã cài toolchain SP1 MỚI NHẤT (vd 1.94-dev), lệch với
crate SP1 pin 6.3.1. cargo-prove mới truyền cờ mà rustc trong crate cũ không hiểu.

**Sửa: pin toolchain SP1 về đúng 6.3.1** (khớp sp1-sdk/sp1-zkvm/sp1-build trong Cargo.toml):
```bash
sp1up --version v6.3.1
cargo prove --version    # xác nhận đã đổi
```
Rồi xóa cache guest cũ và chạy lại:
```bash
rm -rf sp1_verify/guest/target sp1_verify/host/target
cd sp1_verify/host && cargo run --release -- --execute
```

Cách khác (KHÔNG khuyến nghị): nâng toàn bộ crate SP1 lên bản mới nhất khớp toolchain —
rủi ro làm sống lại xung đột generic-array/serde đã dập, và API ProverClient có thể đổi.

## ⚠️ Kiến trúc TÁCH 2 tiến trình (bắt buộc, do xung đột dependency)

`sp1-sdk` khóa `generic-array =1.1.0`, còn `nova-snark 0.71` cần `^1.2.0` — KHÔNG cùng
tồn tại trong một crate. Giải pháp: tách làm hai binary giao tiếp qua FILE:

- **bundle_gen/** — dùng nova + pipeline Engram, sinh `bundle.bin` + `vk.bin`. KHÔNG có sp1-sdk.
- **host/** — chỉ sp1-sdk, đọc 2 file đó, chạy execute/prove. KHÔNG có nova.

Đây cũng đúng thực tế: bên sinh proof (storage node) và bên wrap SP1 (máy thuê) vốn là
hai tiến trình khác nhau.

## Chạy — THỨ TỰ BẮT BUỘC

### 0. Cài SP1 toolchain (một lần)
```bash
curl -L https://sp1up.succinct.xyz | bash
sp1up
cargo prove --version   # xác nhận
```

### 1. Build guest ELF
```bash
cd guest
cargo prove build       # tạo target/riscv32im-succinct-zkvm-elf/release/engram-guest
```

### 2. Sinh bundle (dùng nova, KHÔNG cần SP1)
```bash
cd ../bundle_gen
cargo run --release -- --challenges 3 --out ../artifacts   # tạo bundle.bin + vk.bin
```

### 3. EXECUTE — đếm cycles (LÀM TRƯỚC khi prove, rẻ)
```bash
cd ../host
cargo run --release -- --execute       # đọc ../artifacts/*.bin
```
Đọc `TỔNG CYCLES`. **Đây là con số quyết định.** Diễn giải:
- Vài chục triệu cycles/proof → tốt, đi tiếp.
- Vài trăm triệu+/proof → nút cổ chai (nhiều khả năng ở secondary IPA/Grumpkin). Xem "Nếu
  cycles quá lớn".

Chạy với `--challenges 1,3,5,10` để thấy cycles scale theo số bước fold.

### 4. PROVE — sinh Groth16 (chỉ khi cycles chấp nhận được)
```bash
cargo run --release -- --prove
```
Cần Docker + RAM lớn (16GB+). Sinh `groth16_proof.bin` — calldata cho EVM contract.

## Chướng ngại bạn SẼ gặp (và cách xử lý)

Vì chưa chạy thật, đây là các điểm nhiều khả năng cần chỉnh, theo thứ tự xác suất:

1. **rayon trên riscv.** Đường verify của Spartan KHÔNG gọi rayon (đã grep), nhưng nova vẫn
   `use rayon` ở phạm vi crate → có thể lỗi link. SP1 thường patch được rayon qua
   `[patch.crates-io]` trỏ về rayon shim đơn luồng của SP1, hoặc dùng bản nova đã s`sp1-patch`.
   Nếu lỗi: thêm patch rayon vào `guest/Cargo.toml`.

2. **getrandom.** Verify là deterministic nhưng nova link getrandom. Thêm vào guest:
   ```toml
   getrandom = { version = "0.2", features = ["custom"] }
   ```
   hoặc dùng patch getrandom của SP1.

3. **Version SP1.** File này ghi `sp1-zkvm = "4.0.0"` / `sp1-sdk = "4.0.0"` làm chỗ dựa. Kiểm
   version mới nhất và PIN cho khớp `cargo prove`. API `ProverClient` đổi giữa các major.

4. **halo2curves.** ĐÃ ổn: nova tự tắt `asm` cho target ≠ x86_64. Không cần làm gì.

5. **k256/crypto precompiles.** SP1 có patch tăng tốc BN254 pairing + keccak. Thêm
   `[patch.crates-io]` cho substrate-bn/sha3 nếu muốn giảm cycles mạnh (~20x cho pairing).

## Nếu cycles quá lớn (thứ tự ưu tiên)

1. Patch phép nhân trường halo2curves bằng syscall `uint256_mulmod` của SP1.
2. Giảm `challenges_per_epoch` (circuit nhỏ hơn → secondary IPA MSM nhỏ hơn).
3. Bật precompile BN254 pairing (patch substrate-bn) — giúp phần primary HyperKZG.
4. Batch nhiều IPA check bằng random linear combination.

## Ghi chú cho paper

- `data_root` hiện là mock. Guest KHÔNG verify inclusion trên Celestia — cần Blobstream
  (có bản SP1 chạy sẵn) hoặc khai báo là **trust assumption** trong Security Discussion.
- `test-utils` đang bật cho HyperKZG (SRS random tau). Số cho paper phải chuyển sang
  `setup_with_ptau_dir` + ptau thật.
- Metric cần đo ở bước execute: **tổng cycles, cycles/proof, syscall breakdown** (primary vs
  secondary lộ qua syscall counts). Đây là ablation trung tâm cho RQ3.
