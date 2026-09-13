//! PV-STUB GUEST — guest tối giản chỉ để SINH MỘT GROTH16 PROOF THẬT.
//!
//! ══════════════════════════════════════════════════════════════════════════
//! GUEST NÀY KHÔNG VERIFY STORAGE PROOF. ĐỌC KỸ TRƯỚC KHI DÙNG SỐ ĐO.
//! ══════════════════════════════════════════════════════════════════════════
//!
//! LÝ DO TỒN TẠI: guest thật (`sp1_verify/guest`) tốn 56,64·10⁹ cycle cho N=1
//! và local Groth16 của nó bị OOM-kill ở container limit 35 GiB (bằng chứng:
//! results_server_20260809/host_prove_20260809_201507.log). Hệ quả: bốn đại
//! lượng bị bỏ trống trong bảng — Groth16 proof size, public-values size, EVM
//! calldata size, và gas verify on-chain.
//!
//! BA TRONG BỐN ĐẠI LƯỢNG ĐÓ KHÔNG PHỤ THUỘC GUEST PROGRAM. Wrapper Groth16
//! của SP1 là một circuit CỐ ĐỊNH với đúng 2 public input; ELF của guest chỉ đi
//! vào đó dưới dạng `programVKey` (một bytes32). Chính comment đầu
//! `EngramAttestation.sol` đã ghi điều này:
//!
//!   "SP1Verifier tự băm publicValues thành MỘT digest rồi đưa vào Groth16
//!    cùng vkey — luôn đúng 2 public input, bất kể struct có bao nhiêu trường."
//!
//! Nên: proof size, PV size, calldata size và gas verify đo bằng guest này là
//! HỢP LỆ cho hệ thống thật. `prove_s` và peak RAM proving thì KHÔNG — hai số
//! đó vẫn phải ghi "không đo được" trong Limitations.
//!
//! ══════════════════════════════════════════════════════════════════════════
//! GUEST NÀY LÀM GÌ
//! ══════════════════════════════════════════════════════════════════════════
//! 1. Đọc đúng 256 byte public values do host dựng.
//! 2. Parse bằng `sp1_shared::PublicValues::from_packed` — CÙNG một hàm mà
//!    guest thật và Solidity dùng, nên không có nguy cơ lệch bố cục.
//! 3. TỰ TÍNH LẠI `new_state_root = keccak(prev ‖ batch ‖ results ‖ epoch_be8)`
//!    và assert khớp. Nhờ bước này, proof sinh ra CHỨNG MINH công thức chuỗi
//!    trạng thái đã được thực thi trong zkVM — nghĩa là check
//!    `NewStateRootMismatch` của contract lần đầu được đối chiếu với một proof
//!    THẬT, chứ không phải với PV tự dựng trong test.
//! 4. Commit bằng `commit_slice(&pv.to_packed())` — KHÔNG phải `io::commit(&pv)`.
//!    Lý do endianness: xem sp1_shared/src/lib.rs.

#![no_main]
sp1_zkvm::entrypoint!(main);

use sp1_shared::PublicValues;
use tiny_keccak::{Hasher, Keccak};

fn keccak256(data: &[u8]) -> [u8; 32] {
    let mut h = Keccak::v256();
    h.update(data);
    let mut out = [0u8; 32];
    h.finalize(&mut out);
    out
}

pub fn main() {
    // Host ghi vào stdin đúng một `Vec<u8>` dài 256.
    let pv_bytes: Vec<u8> = sp1_zkvm::io::read();
    let pv = PublicValues::from_packed(&pv_bytes)
        .expect("public values phải là bố cục packed 288 byte của sp1_shared");

    // Hai điều kiện mà EngramAttestation.commitEpoch sẽ revert nếu vi phạm.
    // Fail ở đây rẻ hơn nhiều so với fail sau khi đã tốn một lượt prove.
    assert!(pv.num_verified > 0, "num_verified = 0 → EmptyBatchNotAllowed");
    assert_ne!(pv.results_root, [0u8; 32], "results_root = 0 → ResultsRootMissing");

    // Cùng công thức với guest thật (sp1_verify/guest/src/main.rs bước 6) và
    // với contract (abi.encodePacked(prev, batch, results, uint64 epoch)).
    let mut buf = Vec::with_capacity(32 * 5 + 8);
    buf.extend_from_slice(&pv.prev_state_root);
    buf.extend_from_slice(&pv.batch_root);
    buf.extend_from_slice(&pv.results_root);
    buf.extend_from_slice(&pv.snapshot_id);
    buf.extend_from_slice(&pv.storage_vk_digest);
    buf.extend_from_slice(&pv.epoch.to_be_bytes());
    assert_eq!(
        pv.new_state_root,
        keccak256(&buf),
        "new_state_root không khớp keccak(prev‖batch‖results‖snapshot‖storageVk‖epoch_be8)"
    );

    sp1_zkvm::io::commit_slice(&pv.to_packed());
}
