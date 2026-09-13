//! Nguồn tham chiếu duy nhất (Single Source of Truth) cho việc băm mảng byte thành phần tử trường Fr.
//!
//! Trước đây, logic chia khối 31-byte bị lặp lại ở 5 vị trí khác nhau (sealing.rs, simulator_runner,
//! smoke_bn254, debug_cs, attack_chunk). Sự thiếu đồng bộ giữa các vị trí này có thể dẫn đến việc
//! host và circuit bị lệch dữ liệu một cách thầm lặng, gây lỗi không rõ nguyên nhân khi tạo proof,
//! hoặc nghiêm trọng hơn là làm mất hiệu lực của ràng buộc sở hữu (possession constraint).
//! Module này tập trung logic vào một nơi duy nhất và định nghĩa:
//!
//! ```text
//! bytes_to_fr(b) := fold_limbs(b.len(), bytes_to_limbs(b))
//! ```
//!
//! Nhờ đó, digest (sử dụng trong quá trình sealing) và các limbs (dùng làm witness cho possession 
//! trong circuit) luôn được đảm bảo đồng bộ hoàn toàn nhờ kiến trúc mã nguồn thay vì phụ thuộc
//! vào quá trình kiểm duyệt thủ công.
//!
//! Circuit trong `proving.rs` tái hiện chính xác logic của hàm `fold_limbs` thông qua `hash_2_gadget`.

use crate::poseidon2::hash_2;
use crate::Fr;
use ff::PrimeField;

/// Kích thước tính bằng byte của mỗi limb. Do 31 < 32, mọi limb luôn có giá trị < 2^248 < modulus BN254.
/// Điều này đảm bảo `Fr::from_repr` luôn trả về dạng chuẩn (canonical) mà không cần xử lý dự phòng.
pub const LIMB_BYTES: usize = 31;

/// Tính toán số lượng limb cần thiết cho một khối dữ liệu có kích thước `byte_len` (làm tròn lên).
/// Ví dụ: với khối 4096 bytes, ta sẽ có 132 phần 31-byte đầy và 1 phần 4-byte, tổng cộng 133 limb.
pub const fn num_limbs(byte_len: usize) -> usize {
    byte_len.div_ceil(LIMB_BYTES)
}

/// Chia mảng byte thành các limb có kích thước 31-byte (little-endian, điền thêm số không ở cuối nếu cần).
pub fn bytes_to_limbs(bytes: &[u8]) -> Vec<Fr> {
    bytes
        .chunks(LIMB_BYTES)
        .map(|window| {
            let mut repr = [0u8; 32];
            repr[..window.len()].copy_from_slice(window);
            // Đảm bảo an toàn: repr[31] == 0 luôn đúng vì window.len() <= 31 → giá trị < 2^248.
            Fr::from_repr(repr.into()).expect("Limb 31-byte luôn là phần tử hợp lệ trong trường BN254")
        })
        .collect()
}

/// Gộp các limb thành một digest duy nhất với công thức: `acc_0 = Fr(byte_len)`, `acc_{k+1} = H(acc_k, limb_k)`.
///
/// Giá trị `byte_len` được sử dụng để khởi tạo accumulator nhằm ngăn chặn tấn công mở rộng chiều dài 
/// (length-extension attack) giữa các khối có kích thước khác nhau. Circuit đảm bảo `acc_0` bằng
/// với hằng số `chunk_size_bytes`.
pub fn fold_limbs(byte_len: usize, limbs: &[Fr]) -> Fr {
    let mut acc = Fr::from(byte_len as u64);
    for limb in limbs {
        acc = hash_2(acc, *limb);
    }
    acc
}

/// Băm mảng byte thành phần tử trường Fr. Hàm này được sử dụng trong quá trình sealing (D_i) 
/// cũng như cho các chuỗi định danh như replica_id và beacon.
pub fn bytes_to_fr(bytes: &[u8]) -> Fr {
    fold_limbs(bytes.len(), &bytes_to_limbs(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn num_limbs_khop_voi_chunk_4kb() {
        assert_eq!(num_limbs(4096), 133); // 132 × 31 + 4
        assert_eq!(num_limbs(31), 1);
        assert_eq!(num_limbs(32), 2);
        assert_eq!(bytes_to_limbs(&vec![0u8; 4096]).len(), num_limbs(4096));
    }

    /// Bất biến cốt lõi: digest được commit trong quá trình sealing BẮT BUỘC phải khớp với
    /// kết quả fold của các limb mà circuit sử dụng làm witness. Nếu kiểm thử này thất bại,
    /// ràng buộc sở hữu (possession constraint) sẽ không còn giá trị bảo mật.
    #[test]
    fn digest_bang_fold_cua_limbs() {
        let chunk: Vec<u8> = (0..4096).map(|i| (i * 31 % 251) as u8).collect();
        let limbs = bytes_to_limbs(&chunk);
        assert_eq!(bytes_to_fr(&chunk), fold_limbs(chunk.len(), &limbs));
    }

    #[test]
    fn doi_mot_bit_thi_doi_digest() {
        let chunk = vec![7u8; 4096];
        let mut khac = chunk.clone();
        khac[2000] ^= 0x01;
        assert_ne!(bytes_to_fr(&chunk), bytes_to_fr(&khac));
    }
}
