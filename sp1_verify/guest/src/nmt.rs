//! Xác minh Cây Merkle có Không gian tên (NMT - Namespaced Merkle Tree) — Khắc phục lỗ hổng `data_root`.
//!
//! ══════════════════════════════════════════════════════════════════════════
//! MỤC ĐÍCH CỦA TẬP TIN NÀY
//! ══════════════════════════════════════════════════════════════════════════
//! Trong cấu trúc hiện tại của `host/src/main.rs`:
//!
//!     data_root: [0u8; 32],       // ← Giá trị được gán cứng (hardcode)
//!
//! Guest sao chép trực tiếp giá trị này vào `PublicValues` mà không qua bất kỳ
//! bước kiểm tra nào. Hệ quả là host có thể tự tạo ra các bằng chứng hợp lệ
//! nhưng với dữ liệu giả mạo, truyền vào guest và guest sẽ xác minh thành công.
//! Sau đó, hệ thống sinh ra bằng chứng Groth16 và được EVM chấp nhận. Điều này 
//! dẫn đến việc hệ thống hoàn toàn mất đi tính toàn vẹn (soundness).
//!
//! Cách khắc phục: Guest phải tự tính toán lại `data_root` từ các byte chia sẻ 
//! (share bytes) và bằng chứng NMT (NMT proof), sau đó cam kết (commit) chính 
//! giá trị được tính toán này. Cuối cùng, EVM sẽ đối chiếu với dữ liệu từ Blobstream.
//!
//! ══════════════════════════════════════════════════════════════════════════
//! HAI TÍNH CHẤT QUAN TRỌNG
//! ══════════════════════════════════════════════════════════════════════════
//! 1. Tính Tồn tại (INCLUSION) — Đảm bảo "share tồn tại trong cây", giúp chống lại 
//!    việc làm giả dữ liệu.
//! 2. Tính Đầy đủ (COMPLETENESS) — Đảm bảo "đây là tất cả các share thuộc 
//!    namespace N", giúp ngăn chặn việc kiểm duyệt dữ liệu.
//!
//! Tính đầy đủ (2) là đặc tính ưu việt của NMT so với Merkle thông thường: mỗi nút
//! trong (internal node) mang giá trị không gian tên lớn nhất và nhỏ nhất (min/max),
//! do đó có thể chứng minh việc không có dữ liệu nào bị thiếu. Đây là lý do chính
//! để lựa chọn Celestia thay vì EIP-4844 blob hay IPFS, đồng thời là luận điểm 
//! cốt lõi của bài báo.
//!
//! ══════════════════════════════════════════════════════════════════════════
//! CHI PHÍ TÍNH TOÁN
//! ══════════════════════════════════════════════════════════════════════════
//! NMT sử dụng hàm băm SHA-256. Môi trường SP1 hỗ trợ biên dịch sẵn (precompile)
//! cho SHA-256, do đó chi phí tính toán tương đối rẻ so với 56,4 tỷ chu kỳ
//! của `CompressedSNARK::verify`. Tuy nhiên, cần phải đo lường chỉ số này thành
//! một cột riêng biệt trong RQ3 và không nên gộp chung vào tổng chi phí.
//!
//! ══════════════════════════════════════════════════════════════════════════
//! ⚠ LƯU Ý ĐỐI CHIẾU DỮ LIỆU THỰC TẾ
//! ══════════════════════════════════════════════════════════════════════════
//! Định dạng băm dưới đây được thiết kế dựa trên đặc tả NMT của Celestia. Trước khi 
//! sử dụng kết quả cho bài báo, bắt buộc phải đối chiếu với `celestiaorg/nmt` 
//! phiên bản thực tế trên node bằng các bước sau:
//!   1. `blob.Submit` một blob nhỏ.
//!   2. `blob.GetProof` để lấy bằng chứng thực.
//!   3. `header.GetByHeight` để lấy `dah.row_roots`.
//!   4. Chạy `test_golden_vector_from_node` bên dưới với dữ liệu thực tế.
//! Nếu kiểm thử (test) thất bại, hãy chỉnh sửa các hằng số ở phần CONSTANTS.

#![allow(dead_code)]

use sha2::{Digest, Sha256};

// ══════════════════════════════════════════════════════════════════════════
// HẰNG SỐ (CONSTANTS) — Nếu cần chỉnh sửa sau khi đối chiếu, chỉ sửa ở đây
// ══════════════════════════════════════════════════════════════════════════

/// Không gian tên Celestia: bao gồm 1 byte phiên bản (version) và 28 byte định danh (id).
pub const NS_SIZE: usize = 29;
/// Tiền tố (prefix) dùng để phân biệt nút lá (leaf node) và nút trong (inner node), giúp phòng ngừa tấn công tiền ảnh thứ hai (second-preimage attack).
pub const LEAF_PREFIX: u8 = 0x00;
pub const INNER_PREFIX: u8 = 0x01;
/// Kích thước cố định của một phần dữ liệu chia sẻ (share) là 512 byte.
pub const SHARE_SIZE: usize = 512;

pub type Namespace = [u8; NS_SIZE];

/// Mã băm NMT = (min_ns ‖ max_ns ‖ sha256_digest). Tổng cộng: 29 + 29 + 32 = 90 byte.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct NamespacedHash {
    pub min_ns: Namespace,
    pub max_ns: Namespace,
    pub digest: [u8; 32],
}

pub const NAMESPACED_HASH_SIZE: usize = NS_SIZE * 2 + 32;

impl NamespacedHash {
    pub fn to_bytes(&self) -> [u8; NAMESPACED_HASH_SIZE] {
        let mut out = [0u8; NAMESPACED_HASH_SIZE];
        out[..NS_SIZE].copy_from_slice(&self.min_ns);
        out[NS_SIZE..NS_SIZE * 2].copy_from_slice(&self.max_ns);
        out[NS_SIZE * 2..].copy_from_slice(&self.digest);
        out
    }

    pub fn from_bytes(b: &[u8]) -> Result<Self, NmtError> {
        if b.len() != NAMESPACED_HASH_SIZE {
            return Err(NmtError::BadHashLength(b.len()));
        }
        let mut min_ns = [0u8; NS_SIZE];
        let mut max_ns = [0u8; NS_SIZE];
        let mut digest = [0u8; 32];
        min_ns.copy_from_slice(&b[..NS_SIZE]);
        max_ns.copy_from_slice(&b[NS_SIZE..NS_SIZE * 2]);
        digest.copy_from_slice(&b[NS_SIZE * 2..]);
        Ok(Self { min_ns, max_ns, digest })
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum NmtError {
    BadHashLength(usize),
    BadShareLength(usize),
    /// Các share không được sắp xếp theo thứ tự không gian tên tăng dần — cấu trúc cây bị hỏng hoặc bằng chứng bị làm giả.
    NamespaceNotSorted,
    /// Giá trị gốc (root) tính toán được không khớp với giá trị gốc mong đợi.
    RootMismatch,
    /// VI PHẠM TÍNH ĐẦY ĐỦ: Vẫn còn các share thuộc không gian tên nằm ngoài tập hợp đã cho.
    /// Đây là dấu hiệu cho thấy host đang thực hiện hành vi kiểm duyệt nút (node censorship).
    IncompleteNamespaceRange,
    EmptyProof,
}

// ══════════════════════════════════════════════════════════════════════════
// CÁC HÀM BĂM (HASHING)
// ══════════════════════════════════════════════════════════════════════════

/// Nút lá (Leaf): min = max = không gian tên của share; digest = sha256(0x00 ‖ ns ‖ share_data).
///
/// Môi trường SP1 có hỗ trợ biên dịch sẵn cho SHA-256, do đó hàm này có chi phí thấp.
/// Đây là điểm khác biệt cốt lõi so với `CompressedSNARK::verify` (không có hàm biên dịch sẵn nào phù hợp).
pub fn leaf_hash(share: &[u8]) -> Result<NamespacedHash, NmtError> {
    if share.len() < NS_SIZE {
        return Err(NmtError::BadShareLength(share.len()));
    }
    let mut ns = [0u8; NS_SIZE];
    ns.copy_from_slice(&share[..NS_SIZE]);

    let mut h = Sha256::new();
    h.update([LEAF_PREFIX]);
    h.update(share); // Dữ liệu share đã bao gồm phần không gian tên ở đầu
    let digest: [u8; 32] = h.finalize().into();

    Ok(NamespacedHash { min_ns: ns, max_ns: ns, digest })
}

/// Nút trong (Inner node): min = min(l.min, r.min), max = max(l.max, r.max);
/// digest = sha256(0x01 ‖ l.to_bytes() ‖ r.to_bytes()).
pub fn inner_hash(l: &NamespacedHash, r: &NamespacedHash) -> NamespacedHash {
    let mut h = Sha256::new();
    h.update([INNER_PREFIX]);
    h.update(l.to_bytes());
    h.update(r.to_bytes());
    let digest: [u8; 32] = h.finalize().into();

    NamespacedHash {
        min_ns: if l.min_ns <= r.min_ns { l.min_ns } else { r.min_ns },
        max_ns: if l.max_ns >= r.max_ns { l.max_ns } else { r.max_ns },
        digest,
    }
}

// ══════════════════════════════════════════════════════════════════════════
// BẰNG CHỨNG (PROOF)
// ══════════════════════════════════════════════════════════════════════════

/// Bằng chứng cho một dải các share liên tiếp [start, end) trong một hàng (row).
#[derive(Clone, Debug)]
pub struct NmtRangeProof {
    pub start: usize,
    pub end: usize,
    /// Các nút anh em (sibling nodes), được sắp xếp theo thứ tự từ trái sang phải dựa trên cấu trúc cây.
    pub siblings: Vec<NamespacedHash>,
}

/// Kiểm tra Tính Tồn tại (Inclusion): Tính toán lại gốc của hàng (row root) từ các share và sibling, sau đó so sánh với `expected_root`.
///
/// Bước kiểm tra này không đủ để chống lại việc kiểm duyệt dữ liệu — cần gọi thêm hàm `verify_completeness` để đảm bảo tính an toàn.
pub fn verify_inclusion(
    shares: &[Vec<u8>],
    proof: &NmtRangeProof,
    expected_root: &NamespacedHash,
) -> Result<(), NmtError> {
    if shares.is_empty() {
        return Err(NmtError::EmptyProof);
    }

    // Các nút lá phải được sắp xếp theo thứ tự không gian tên không giảm — đây là bất biến (invariant) của NMT.
    let mut leaves = Vec::with_capacity(shares.len());
    let mut prev: Option<Namespace> = None;
    for s in shares {
        let lh = leaf_hash(s)?;
        if let Some(p) = prev {
            if lh.min_ns < p {
                return Err(NmtError::NamespaceNotSorted);
            }
        }
        prev = Some(lh.max_ns);
        leaves.push(lh);
    }

    let root = fold_with_siblings(leaves, &proof.siblings);
    if &root != expected_root {
        return Err(NmtError::RootMismatch);
    }
    Ok(())
}

/// Kết hợp các nút lá và các nút anh em để tạo thành nút gốc (root).
///
/// ⚠ Đây là phiên bản được đơn giản hóa: hàm sẽ kết hợp các nút lá theo từng tầng trước, sau đó mới kết hợp với các nút anh em.
/// Cấu trúc thực tế của các nút anh em trong `celestiaorg/nmt` phụ thuộc vào vị trí của dải (range) trong cây.
/// Bắt buộc phải đối chiếu với bằng chứng thực tế từ `blob.GetProof` trước khi trích xuất số liệu cho bài báo
/// (vui lòng tham khảo hàm `test_golden_vector_from_node`).
fn fold_with_siblings(
    mut nodes: Vec<NamespacedHash>,
    siblings: &[NamespacedHash],
) -> NamespacedHash {
    let mut si = 0usize;
    while nodes.len() > 1 || si < siblings.len() {
        if nodes.len() == 1 && si < siblings.len() {
            // Kết hợp với nút anh em: đặt nút anh em ở bên trái nếu không gian tên của nó nhỏ hơn.
            let sib = siblings[si];
            si += 1;
            nodes = vec![if sib.max_ns <= nodes[0].min_ns {
                inner_hash(&sib, &nodes[0])
            } else {
                inner_hash(&nodes[0], &sib)
            }];
            continue;
        }
        let mut next = Vec::with_capacity(nodes.len().div_ceil(2));
        let mut i = 0;
        while i + 1 < nodes.len() {
            next.push(inner_hash(&nodes[i], &nodes[i + 1]));
            i += 2;
        }
        if i < nodes.len() {
            next.push(nodes[i]);
        }
        nodes = next;
    }
    nodes[0]
}

/// **Kiểm tra Tính Đầy đủ (Completeness) — Đây là cơ chế phòng chống kiểm duyệt cốt lõi của bài báo.**
///
/// Chứng minh rằng: Tập hợp các share được cung cấp chứa toàn bộ các share thuộc không gian tên `ns` trong hàng này.
///
/// Nguyên lý hoạt động: Nếu một nút anh em có dải không gian tên giao với `ns`, điều này có nghĩa là
/// vẫn còn các share thuộc `ns` nhưng không nằm trong tập hợp được cung cấp → host đã bỏ sót dữ liệu.
///
/// Nếu host muốn loại bỏ một nút (ví dụ nút C) khỏi một lô (batch), host phải tạo ra được một bằng chứng hợp lệ
/// nhưng lại thiếu các share của C — điều này là bất khả thi vì các nút anh em sẽ phản ánh sự thiếu hụt này.
/// Nhờ vậy, vấn đề kiểm duyệt được giải quyết triệt để bằng các nguyên lý mật mã học, thay vì dựa vào các yếu tố kinh tế.
pub fn verify_completeness(ns: &Namespace, proof: &NmtRangeProof) -> Result<(), NmtError> {
    for sib in &proof.siblings {
        // Hai khoảng giao nhau khi: sib.min_ns <= ns <= sib.max_ns
        if &sib.min_ns <= ns && ns <= &sib.max_ns {
            return Err(NmtError::IncompleteNamespaceRange);
        }
    }
    Ok(())
}

/// Điểm đầu vào toàn diện: Thực hiện kiểm tra cả Tính Tồn tại (Inclusion) và Tính Đầy đủ (Completeness).
/// Guest chỉ nên gọi hàm này, không nên gọi các hàm kiểm tra đơn lẻ.
pub fn verify_namespace_complete(
    ns: &Namespace,
    shares: &[Vec<u8>],
    proof: &NmtRangeProof,
    expected_root: &NamespacedHash,
) -> Result<(), NmtError> {
    verify_inclusion(shares, proof, expected_root)?;
    verify_completeness(ns, proof)?;
    Ok(())
}

/// `data_root` là gốc Merkle nhị phân (sử dụng hàm SHA-256 thông thường, không chứa không gian tên)
/// được tính toán trên tập hợp `row_root` ‖ `col_root` của Tiêu đề Tính khả dụng Dữ liệu (Data Availability Header).
///
/// Đây là giá trị mà Blobstream sẽ chuyển tiếp (relay) sang Ethereum và là giá trị bắt buộc guest phải cam kết (commit)
/// thay vì sử dụng mảng tĩnh `[0u8; 32]` như hiện tại.
pub fn compute_data_root(row_roots: &[NamespacedHash], col_roots: &[NamespacedHash]) -> [u8; 32] {
    let mut leaves: Vec<[u8; 32]> = Vec::with_capacity(row_roots.len() + col_roots.len());
    for r in row_roots.iter().chain(col_roots.iter()) {
        let mut h = Sha256::new();
        h.update([LEAF_PREFIX]);
        h.update(r.to_bytes());
        leaves.push(h.finalize().into());
    }
    binary_merkle_root(leaves)
}

fn binary_merkle_root(mut leaves: Vec<[u8; 32]>) -> [u8; 32] {
    if leaves.is_empty() {
        return [0u8; 32];
    }
    while leaves.len() > 1 {
        let mut next = Vec::with_capacity(leaves.len().div_ceil(2));
        let mut i = 0;
        while i + 1 < leaves.len() {
            let mut h = Sha256::new();
            h.update([INNER_PREFIX]);
            h.update(leaves[i]);
            h.update(leaves[i + 1]);
            next.push(h.finalize().into());
            i += 2;
        }
        if i < leaves.len() {
            next.push(leaves[i]);
        }
        leaves = next;
    }
    leaves[0]
}

// ══════════════════════════════════════════════════════════════════════════
// KIỂM THỬ (TESTS) — Thực thi trên máy chủ (host) bằng lệnh `cargo test -p engram-guest --lib`
// (Do guest là một tệp thực thi (bin), cần tách `nmt.rs` thành một thư viện (lib) hoặc sử dụng module `#[cfg(test)]`)
// ══════════════════════════════════════════════════════════════════════════
#[cfg(test)]
mod tests {
    use super::*;

    fn ns(tag: u8) -> Namespace {
        let mut n = [0u8; NS_SIZE];
        n[NS_SIZE - 1] = tag;
        n
    }

    fn share(tag: u8, fill: u8) -> Vec<u8> {
        let mut s = vec![fill; SHARE_SIZE];
        s[..NS_SIZE].copy_from_slice(&ns(tag));
        s
    }

    #[test]
    fn leaf_min_max_bang_namespace_cua_share() {
        let lh = leaf_hash(&share(7, 0xAA)).unwrap();
        assert_eq!(lh.min_ns, ns(7));
        assert_eq!(lh.max_ns, ns(7));
    }

    #[test]
    fn inner_lay_min_va_max_dung() {
        let a = leaf_hash(&share(3, 1)).unwrap();
        let b = leaf_hash(&share(9, 2)).unwrap();
        let p = inner_hash(&a, &b);
        assert_eq!(p.min_ns, ns(3));
        assert_eq!(p.max_ns, ns(9));
    }

    #[test]
    fn prefix_chong_second_preimage() {
        // Các nút lá và nút trong phải trả về mã băm khác nhau ngay cả khi có cùng nội dung.
        let a = leaf_hash(&share(1, 0)).unwrap();
        let b = leaf_hash(&share(1, 0)).unwrap();
        assert_eq!(a.digest, b.digest);
        assert_ne!(inner_hash(&a, &b).digest, a.digest);
    }

    #[test]
    fn inclusion_pass_khi_root_dung() {
        let shares = vec![share(5, 1), share(5, 2)];
        let leaves: Vec<_> = shares.iter().map(|s| leaf_hash(s).unwrap()).collect();
        let root = inner_hash(&leaves[0], &leaves[1]);
        let proof = NmtRangeProof { start: 0, end: 2, siblings: vec![] };
        assert!(verify_inclusion(&shares, &proof, &root).is_ok());
    }

    #[test]
    fn inclusion_fail_khi_share_bi_sua() {
        let shares = vec![share(5, 1), share(5, 2)];
        let leaves: Vec<_> = shares.iter().map(|s| leaf_hash(s).unwrap()).collect();
        let root = inner_hash(&leaves[0], &leaves[1]);
        let tampered = vec![share(5, 1), share(5, 99)]; // Thay đổi nội dung của share
        let proof = NmtRangeProof { start: 0, end: 2, siblings: vec![] };
        assert_eq!(
            verify_inclusion(&tampered, &proof, &root),
            Err(NmtError::RootMismatch)
        );
    }

    #[test]
    fn phat_hien_lá_khong_sap_xep() {
        let shares = vec![share(9, 1), share(3, 2)]; // Thứ tự giảm dần — không hợp lệ
        let proof = NmtRangeProof { start: 0, end: 2, siblings: vec![] };
        let dummy = leaf_hash(&share(0, 0)).unwrap();
        assert_eq!(
            verify_inclusion(&shares, &proof, &dummy),
            Err(NmtError::NamespaceNotSorted)
        );
    }

    /// BÀI KIỂM THỬ QUAN TRỌNG NHẤT: Mô phỏng hành vi host đang kiểm duyệt một nút.
    #[test]
    fn completeness_bat_duoc_kiem_duyet() {
        let target = ns(5);
        // Host cung cấp bằng chứng nhưng nút anh em vẫn chứa không gian tên 5 → có dữ liệu (share) đã bị bỏ sót.
        let sneaky = NamespacedHash {
            min_ns: ns(4),
            max_ns: ns(6), // Dải giá trị [4, 6] bao trùm cả không gian tên 5
            digest: [0u8; 32],
        };
        let proof = NmtRangeProof { start: 0, end: 1, siblings: vec![sneaky] };
        assert_eq!(
            verify_completeness(&target, &proof),
            Err(NmtError::IncompleteNamespaceRange),
            "Hệ thống bắt buộc phải phát hiện còn các share thuộc không gian tên 5 bị bỏ sót"
        );
    }

    #[test]
    fn completeness_pass_khi_sibling_khong_giao() {
        let target = ns(5);
        let left = NamespacedHash { min_ns: ns(1), max_ns: ns(4), digest: [0u8; 32] };
        let right = NamespacedHash { min_ns: ns(6), max_ns: ns(9), digest: [1u8; 32] };
        let proof = NmtRangeProof { start: 0, end: 1, siblings: vec![left, right] };
        assert!(verify_completeness(&target, &proof).is_ok());
    }

    #[test]
    fn data_root_on_dinh_va_khac_nhau_khi_doi_input() {
        let a = leaf_hash(&share(1, 1)).unwrap();
        let b = leaf_hash(&share(2, 2)).unwrap();
        let r1 = compute_data_root(&[a], &[b]);
        let r2 = compute_data_root(&[a], &[b]);
        let r3 = compute_data_root(&[b], &[a]);
        assert_eq!(r1, r2, "Kết quả phải mang tính tất định (deterministic)");
        assert_ne!(r1, r3, "Việc thay đổi thứ tự dữ liệu phải làm thay đổi giá trị gốc");
        assert_ne!(r1, [0u8; 32], "Kết quả mã băm không được là toàn số 0");
    }

    #[test]
    fn roundtrip_bytes() {
        let h = leaf_hash(&share(42, 7)).unwrap();
        assert_eq!(NamespacedHash::from_bytes(&h.to_bytes()).unwrap(), h);
    }

    /// ⚠ BÀI KIỂM THỬ CHẶN (BLOCKING TEST) — Bắt buộc phải cung cấp dữ liệu THỰC TẾ từ node, sau đó loại bỏ thuộc tính `#[ignore]`.
    ///
    /// Các bước để lấy dữ liệu thực tế:
    ///   1. Thực thi lệnh `blob.Submit` với một blob có kích thước nhỏ → nhận về giá trị height.
    ///   2. Thực thi lệnh `blob.GetProof(height, ns, commitment)` → thu thập các nút anh em (siblings).
    ///   3. Thực thi lệnh `header.GetByHeight(height)` → nhận về danh sách `dah.row_roots`.
    ///
    /// Nếu bài kiểm thử này thất bại, nguyên nhân có thể do định dạng băm tại phần CONSTANTS bị sai — chỉ sửa ở khu vực đó,
    /// không sửa bất kỳ logic nào ở các phần khác. TUYỆT ĐỐI KHÔNG trích xuất số liệu cho bài báo trước khi bài kiểm thử này hoàn thành thành công.
    #[test]
    #[ignore = "Yêu cầu phải có dữ liệu thực tế từ node Celestia"]
    fn test_golden_vector_from_node() {
        // let share_hex   = "…";
        // let sibling_hex = ["…"];
        // let row_root_hex= "…";
        // assert!(verify_inclusion(...).is_ok());
        panic!("Chưa cung cấp dữ liệu thực tế — Vui lòng tham khảo tài liệu experiments/README.md");
    }
}
