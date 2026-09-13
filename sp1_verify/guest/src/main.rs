//! SP1 GUEST — verify batch CompressedSNARK trong zkVM.
//!
//! Compile cho target `riscv32im-succinct-zkvm-elf`. Đây là chương trình mà SP1
//! chứng minh đã-chạy-đúng: nó verify từng proof của storage node, tính batch_root,
//! rồi commit public values để EVM kiểm.
//!
//! PHÁT HIỆN KIẾN TRÚC (đã xác minh từ source nova 0.71.1):
//!   - CompressedSNARK::verify() KHÔNG gọi synthesize() của circuit.
//!   - Type circuit C chỉ là PhantomData<C> trong CompressedSNARK, verify không dùng arity().
//!   → Guest KHÔNG cần core_primitives (lazy_static/rayon). Chỉ cần một circuit STUB
//!     có đúng arity()=7 để khớp generic. Đây là lý do guest nhẹ đến bất ngờ.
//!
//! LÁ CHẮN TIN CẬY: prover chạy guest này là máy THUÊ, không cần tin. Groth16 wrap của
//! SP1 chứng minh guest chạy đúng → EVM chỉ tin mật mã.

#![no_main]
sp1_zkvm::entrypoint!(main);

// ── NMT: module CÓ, nhưng CHƯA nối vào luồng ──────────────────────────────
// `nmt.rs` cần `sha2`, mà guest/Cargo.toml trước đây không khai — nên kể cả
// thêm `mod nmt;` trần thì cũng KHÔNG compile. Trước đây file 446 dòng đó nằm
// im trong repo không được biên dịch lần nào: nó trông như đã làm xong trong
// khi thực chất chưa từng chạy qua compiler.
//
// Gate sau feature để (a) build mặc định không đổi — dải cycle đã đo vẫn tái
// lập được, (b) có một lệnh CỤ THỂ để kiểm nó biên dịch được:
//
//     cd sp1_verify/guest && cargo check --features nmt
//
// Khi nối thật, nhớ thêm patch sha2 của SP1 để dùng precompile SHA-256 — không
// có nó thì lập luận "NMT rẻ" ở đầu nmt.rs không còn đúng.
#[cfg(feature = "nmt")]
mod nmt;

use core::marker::PhantomData;
use ff::PrimeField;
use nova_snark::frontend::{num::AllocatedNum, ConstraintSystem, SynthesisError};
use nova_snark::nova::{CompressedSNARK, VerifierKey};
use nova_snark::traits::circuit::StepCircuit;
use sp1_shared::{GuestInput, ProofBundle, PublicValues};
use tiny_keccak::{Hasher, Keccak};

// ── Type alias nova (guest-side) — PHẢI khớp prover/src/proving.rs của simulation ──
// (Gộp thẳng vào đây thay vì crate riêng để tránh bug path-dependency của sp1-build.)
pub use nova_snark::provider::hyperkzg::EvaluationEngine as EEPrimary;
pub use nova_snark::provider::ipa_pc::EvaluationEngine as EESecondary;
pub use nova_snark::provider::{Bn256EngineKZG as E1, GrumpkinEngine as E2};
pub use nova_snark::spartan::ppsnark::RelaxedR1CSSNARK as PpSNARK;

pub type S1 = PpSNARK<E1, EEPrimary<E1>>;
pub type S2 = PpSNARK<E2, EESecondary<E2>>;
pub type Scalar = <E1 as nova_snark::traits::Engine>::Scalar; // BN254 Fr

/// Circuit STUB — chỉ để khớp generic của CompressedSNARK. arity() PHẢI = 7 (bằng
/// EngramStepCircuit thật). verify() KHÔNG gọi synthesize() nên thân hàm là trivial;
/// circuit type chỉ là PhantomData<C> trong proof nên stub này không ảnh hưởng verify.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EngramStubCircuit<F: PrimeField = Scalar> {
    _p: PhantomData<F>,
}

impl<F: PrimeField> StepCircuit<F> for EngramStubCircuit<F> {
    fn arity(&self) -> usize {
        7
    }
    fn synthesize<CS: ConstraintSystem<F>>(
        &self,
        _cs: &mut CS,
        z: &[AllocatedNum<F>],
    ) -> Result<Vec<AllocatedNum<F>>, SynthesisError> {
        Ok(z.to_vec())
    }
}

type Vk = VerifierKey<E1, E2, EngramStubCircuit, S1, S2>;
type Snark = CompressedSNARK<E1, E2, EngramStubCircuit, S1, S2>;

fn keccak256(data: &[u8]) -> [u8; 32] {
    let mut h = Keccak::v256();
    h.update(data);
    let mut out = [0u8; 32];
    h.finalize(&mut out);
    out
}

/// Domain-separated commitment to bundle identity, epoch/context and proof.
/// Hashing proof_bytes alone permits cross-epoch/context ambiguity and makes
/// duplicated payloads indistinguishable from distinct assignments.
fn bundle_leaf(bundle: &ProofBundle) -> [u8; 32] {
    let proof_digest = keccak256(&bundle.proof_bytes);
    let mut encoded = Vec::with_capacity(24 + 8 + 8 + 32 * 4 + 4);
    encoded.extend_from_slice(b"ENGRAM_PROOF_BUNDLE_V2");
    encoded.extend_from_slice(&bundle.sector_id.to_be_bytes());
    encoded.extend_from_slice(&bundle.epoch.to_be_bytes());
    encoded.extend_from_slice(&bundle.sealed_root);
    encoded.extend_from_slice(&bundle.beacon);
    encoded.extend_from_slice(&bundle.replica_id);
    encoded.extend_from_slice(&bundle.num_steps.to_be_bytes());
    encoded.extend_from_slice(&proof_digest);
    keccak256(&encoded)
}

/// Merkle-keccak root trên các lá (thứ tự cố định). Lá đơn → chính nó.
/// Số lẻ → nhân đôi lá cuối (quy ước phổ biến, contract phải khớp).
/// Hành động quyết toán mà guest phân biệt được.
///
/// ⚠ Guest CHỈ phân biệt được hai trạng thái, không phải ba. Để kết luận "nút
/// này đáng bị phạt", cần một chữ ký của nhà cung cấp trên bundle để quy trách
/// nhiệm — `ProofBundle` hiện không mang chữ ký nào. Nên một bundle không xác
/// minh được sẽ nhận UNRESOLVED, không phải SLASH.
///
/// Đây là chọn lựa fail-safe: chữ ký giả mạo danh nghĩa nút X không dẫn tới
/// việc phạt X. Phân biệt SLASH với UNRESOLVED thuộc aggregator guest, nơi có
/// chữ ký để đối chiếu với sổ nhà cung cấp.
const ACTION_UNRESOLVED: u8 = 0;
const ACTION_REWARD: u8 = 1;

/// Lá của danh sách quyết toán cho MỘT bundle.
///
/// Chỉ dùng các trường guest thực sự quan sát được. Tiền tố miền tách không
/// gian khoá của lá quyết toán khỏi lá batch (`ENGRAM_PROOF_BUNDLE_V2`), nên
/// không thể dùng lá của cây này làm lá của cây kia.
fn settlement_leaf(bundle: &sp1_shared::ProofBundle, verified: bool) -> [u8; 32] {
    let mut e = Vec::with_capacity(32 + 32 + 8 + 8 + 1);
    e.extend_from_slice(b"ENGRAM_SETTLEMENT_LEAF_V1");
    e.push(0u8); // vách ngăn miền
    e.extend_from_slice(&bundle.replica_id);
    e.extend_from_slice(&bundle.sector_id.to_be_bytes());
    e.extend_from_slice(&bundle.epoch.to_be_bytes());
    e.push(if verified { ACTION_REWARD } else { ACTION_UNRESOLVED });
    keccak256(&e)
}

fn merkle_root(mut leaves: Vec<[u8; 32]>) -> [u8; 32] {
    if leaves.is_empty() {
        return [0u8; 32];
    }
    while leaves.len() > 1 {
        if leaves.len() % 2 == 1 {
            leaves.push(*leaves.last().unwrap());
        }
        let mut next = Vec::with_capacity(leaves.len() / 2);
        for pair in leaves.chunks(2) {
            let mut buf = [0u8; 64];
            buf[..32].copy_from_slice(&pair[0]);
            buf[32..].copy_from_slice(&pair[1]);
            next.push(keccak256(&buf));
        }
        leaves = next;
    }
    leaves[0]
}

/// 32 bytes → Scalar (BN254 Fr). Dùng để dựng z0 từ public inputs.
fn bytes_to_scalar(b: &[u8; 32]) -> Scalar {
    // nova Fr::from_repr nhận little-endian; sealed_root/beacon của ta lưu theo repr
    // little-endian của Fr (xem host: Fr::to_repr()). Nên KHÔNG đảo byte ở đây.
    use ff::PrimeField;
    let mut repr = <Scalar as PrimeField>::Repr::default();
    repr.as_mut().copy_from_slice(b);
    Scalar::from_repr(repr).expect("public input phải là Fr hợp lệ")
}

pub fn main() {
    // ── Đọc input (private) ──
    let input: GuestInput = sp1_zkvm::io::read();
    assert!(!input.bundles.is_empty(), "empty batch is not allowed");
    assert!(input.bundles.len() <= 4_096, "batch exceeds guest bound");
    assert!(input.vk_bytes.len() <= 16 * 1024 * 1024, "vk exceeds guest bound");
    assert!(
        input
            .bundles
            .iter()
            .all(|bundle| {
                bundle.proof_bytes.len() <= 16 * 1024 * 1024
                    && bundle.num_steps <= 4_096
            }),
        "proof bytes or num_steps exceed guest bound"
    );

    // ⚠ RÀO CHẮN: nếu về sau host bắt đầu bơm DaInclusion vào mà guest vẫn lặng
    // lẽ bỏ qua, hệ thống sẽ TRÔNG như đã ràng buộc DA trong khi không hề. Thà
    // dừng ồn ào ở đây còn hơn để paper claim một tính chất không có.
    assert!(
        input.da.is_none(),
        "GuestInput.da có dữ liệu nhưng guest chưa verify NMT — bật feature `nmt` \
         và viết resolve_data_root() trước (xem nmt.rs)"
    );

    // vk dùng chung cho mọi bundle (cùng circuit shape).
    //
    // ⚠ GIẢ ĐỊNH CHƯA THOẢ TRONG PROTOTYPE: điều này chỉ đúng khi mọi bundle
    // được sinh từ CÙNG MỘT PublicParams. Với feature `test-utils` của nova thì
    // `PublicParams::setup` KHÔNG tất định — chạy bundle_gen hai lần cùng seed
    // cho ra hai vk khác hash (đã đo). Nên các bundle phải sinh trong một tiến
    // trình (`bundle_gen --num-bundles N`). Hệ thống THẬT cần
    // `setup_with_ptau_dir` với ptau cố định; đó là trusted-setup assumption
    // phải ghi vào Security Discussion.
    // P35: khóa verifier của storage proof là input riêng, KHÔNG phải SP1
    // programVKey. Commit digest của nó ra public values để contract pin đúng
    // storage relation/setup; nếu thiếu ràng buộc này, Host có thể đưa một VK
    // khác cùng proof được tạo theo circuit yếu hơn mà Guest chuẩn vẫn verify.
    let storage_vk_digest = keccak256(&input.vk_bytes);
    let vk: Vk = bincode::deserialize(&input.vk_bytes).expect("deserialize vk");

    let mut batch_leaves: Vec<[u8; 32]> = Vec::with_capacity(input.bundles.len());
    // ★ Lá quyết toán, GIỮ CÙNG THỨ TỰ với lá batch: chỉ số của một nút trong
    // hai cây bằng nhau, nên nút chỉ cần biết một chỉ số để dựng nhân chứng cho
    // cả hai. Thứ tự do host chọn, nhưng điều đó không ảnh hưởng tính đúng đắn:
    // tập các cặp (replica_id, verified) do chính các bằng chứng quyết định,
    // hoán vị không đổi tập đó. Ép thứ tự chuẩn tắc theo entry_key thuộc
    // aggregator guest, nơi có bảng phân công.
    let mut settle_leaves: Vec<[u8; 32]> = Vec::with_capacity(input.bundles.len());
    let mut num_verified: u32 = 0;

    for bundle in &input.bundles {
        // (1) Lá batch commit toàn bộ context + proof bytes, không chỉ proof bytes.
        //     Lá được thêm cho MỌI bundle, kể cả bundle verify fail: batch_root cam kết
        //     những gì đã publish, còn num_verified nói bao nhiêu cái hợp lệ. Hai đại
        //     lượng khác nhau, không được trộn.
        let leaf = bundle_leaf(bundle);
        batch_leaves.push(leaf);

        // (2) Dựng z0 theo layout EngramStepCircuit:
        //     [epoch, 0, sector_id, sealed_root, beacon, replica_id, replica_id]
        let z0: Vec<Scalar> = alloc_z0(bundle);

        // (3) Deserialize + VERIFY. Đây là phần tốn cycles nhất:
        //     primary = HyperKZG (log-sized, có precompile pairing) — rẻ
        //     secondary = IPA/Grumpkin (MSM tuyến tính, KHÔNG precompile) — đắt
        //
        // ⚠ THAY ĐỔI: trước đây dùng `.expect("proof phải verify PASS")`, tức một
        // proof hỏng làm PANIC cả guest. Hậu quả trong thực nghiệm: guest dừng,
        // KHÔNG commit gì, host đọc public values gặp EOF rồi panic — và toàn bộ
        // ~20 phút đếm cycles bay theo, không phân biệt được "proof sai" với
        // "guest crash".
        //
        // Giờ đếm thay vì panic. Đây cũng là hành vi ĐÚNG theo thiết kế: trường
        // `num_verified` tồn tại chính là để nói "bao nhiêu proof hợp lệ trong
        // batch". Một node gửi proof rác không được phép làm hỏng cả epoch của
        // những node trung thực khác.
        //
        // Contract cũng reject num_verified == 0. Batch completeness/exact-cover
        // vẫn thuộc Aggregator Guest V7, không phải prototype guest này.
        let verified = if bundle.epoch != input.epoch {
            false
        } else {
            match bincode::deserialize::<Snark>(&bundle.proof_bytes) {
                Err(_) => false,
                Ok(proof) => match proof.verify(&vk, bundle.num_steps as usize, &z0) {
                    Err(_) => false,
                    // (4) Sanity: zn[0] phải bằng epoch — chống proof đúng nhưng của epoch khác.
                    Ok(zn) => zn[0] == Scalar::from(bundle.epoch),
                },
            }
        };
        // ★ Lá quyết toán sinh TỪ BIẾN `verified` vừa tính, không từ input.
        //   Đây chính là ràng buộc mà bằng chứng Groth16 khẳng định: danh sách
        //   thưởng/phạt là hàm của kết quả xác minh, không phải của lời khai.
        settle_leaves.push(settlement_leaf(bundle, verified));

        if verified {
            num_verified += 1;
        }
    }

    // (5) batch_root từ các proof đã publish.
    let batch_root = merkle_root(batch_leaves);
    // ★ Guest TỰ TÍNH, không nhận từ host.
    let results_root = merkle_root(settle_leaves);

    // (6) new_state_root = keccak(prev ‖ batch_root ‖ results_root ‖ epoch).
    // Contract sẽ tái kiểm chuỗi; result manifest vì vậy không thể bị thay sau proof.
    // ★ Bind thêm snapshot_id và storage_vk_digest.
    //   keccak(prev ‖ batch ‖ results ‖ snapshot ‖ storageVk ‖ epoch_be8)
    //   Solidity PHẢI tính lại đúng thứ tự này.
    let new_state_root = {
        let mut buf = Vec::with_capacity(32 * 5 + 8);
        buf.extend_from_slice(&input.prev_state_root);
        buf.extend_from_slice(&batch_root);
        buf.extend_from_slice(&results_root);
        buf.extend_from_slice(&input.snapshot_id);
        buf.extend_from_slice(&storage_vk_digest);
        buf.extend_from_slice(&input.epoch.to_be_bytes());
        keccak256(&buf)
    };

    // (7) Commit public values.
    //
    // ⚠ PHẢI là `commit_slice(&pv.to_packed())`, KHÔNG phải `commit(&pv)`.
    // `commit(&pv)` serialize bằng bincode. Với struct này bincode ra ĐÚNG 256
    // byte nên `PV_LEN` check bên Solidity vẫn PASS — nhưng bincode ghi u64/u32
    // LITTLE-endian còn Solidity đọc BIG-endian, nên `epoch` và `num_verified`
    // giải mã thành rác. Đã kiểm chứng bằng unit test trong sp1_shared:
    //     bincode: epoch=1 → 01 00 00 00 00 00 00 00
    //     packed : epoch=1 → 00 00 00 00 00 00 00 01
    // Lỗi này KHÔNG lộ ở forge test (test tự dựng PV bằng abi.encodePacked, vốn
    // big-endian) — chỉ lộ khi nối proof thật vào contract thật.
    //
    // ⚠ data_root: đang CHÉP giá trị host khai, chưa dựng lại từ NMT. Xem rào
    // chắn `input.da.is_none()` ở đầu main() và Limitations của paper.
    let pv = PublicValues {
        epoch: input.epoch,
        batch_root,
        data_root: input.data_root,
        results_root,
        results_data_root: input.results_data_root,
        storage_vk_digest,
        snapshot_id: input.snapshot_id,
        submitter: input.submitter,
        prev_state_root: input.prev_state_root,
        new_state_root,
        num_verified,
    };
    sp1_zkvm::io::commit_slice(&pv.to_packed());
}

/// Dựng z0 từ các trường public của bundle. Layout PHẢI khớp
/// simulator_runner: [epoch, 0, sector_id, sealed_root, beacon, replica_id, replica_id].
fn alloc_z0(b: &sp1_shared::ProofBundle) -> Vec<Scalar> {
    let replica = bytes_to_scalar(&b.replica_id);
    let arr: [Scalar; 7] = [
        Scalar::from(b.epoch),
        Scalar::from(0u64),
        Scalar::from(b.sector_id),
        bytes_to_scalar(&b.sealed_root),
        bytes_to_scalar(&b.beacon),
        replica,
        replica,
    ];
    arr.to_vec()
}
