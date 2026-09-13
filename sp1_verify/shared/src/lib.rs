//! Các cấu trúc dữ liệu thuần túy (pure data structures) được chia sẻ chung giữa host, guest và bundle_gen.
//!
//! QUAN TRỌNG: Crate này KHÔNG phụ thuộc vào thư viện `nova-snark`. Lý do là host chỉ cần sử dụng 
//! các cấu trúc dữ liệu nguyên thủy (như `u64`, `[u8;32]`, `Vec<u8>`) để đọc bundle từ tệp và 
//! nạp chúng vào SP1. Nếu `sp1_shared` thêm `nova-snark` làm dependency, host sẽ vô tình 
//! kéo theo `nova`, dẫn đến xung đột phiên bản của `generic-array` với `sp1-sdk` (do `nova` 
//! yêu cầu phiên bản `^1.2.0`, trong khi `sp1` yêu cầu chặt chẽ ở mức `=1.1.0`).
//!
//! Các type alias (bí danh kiểu) liên quan đến `nova` (như `E1`, `E2`, `S1`, `S2`, `Scalar`) 
//! được định nghĩa tại `guest/bundle_gen`, vì chỉ có hai vị trí này cần sử dụng chúng.

use serde::{Deserialize, Serialize};

/// Các giá trị công khai (Public Values) mà guest cam kết (commit) ra bên ngoài. EVM sẽ giải mã (decode) trực tiếp dựa trên cấu trúc này.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct PublicValues {
    pub epoch: u64,
    pub batch_root: [u8; 32],
    pub data_root: [u8; 32],
    /// Gốc Merkle (Merkle root) của danh sách kết quả quyết toán.
    ///
    /// ★ LƯU Ý: Giá trị này ĐƯỢC TÍNH TOÁN TỰ ĐỘNG BỞI GUEST dựa trên kết quả xác minh 
    /// của từng bundle. Trước đây, host tự cung cấp giá trị này và guest chỉ đơn thuần sao chép 
    /// đầu ra, điều đó đồng nghĩa với việc bằng chứng Groth16 không đảm bảo được tính 
    /// chính xác của danh sách kết quả.
    pub results_root: [u8; 32],
    /// Data root độc lập trên Data Availability (DA) dùng để lưu trữ bản ghi kết quả (result manifest).
    pub results_data_root: [u8; 32],
    /// Mã băm Keccak-256 của `GuestInput.vk_bytes` (khóa xác minh Spartan/Nova).
    /// Hợp đồng (Contract) sẽ lưu cố định digest này hoàn toàn độc lập với `programVKey` của SP1.
    pub storage_vk_digest: [u8; 32],
    /// ★ Định danh bản ghi trạng thái (snapshot ID) của một epoch: bao gồm cam kết 
    /// gốc của danh sách thành viên (membership root), danh sách giao dịch (deals root),
    /// sổ đăng ký nhà cung cấp (provider registry root), beacon và khung chiều cao của DA.
    ///
    /// Nếu thiếu trường này, chuỗi sẽ không thể xác định epoch đang được tính toán 
    /// trên tập hợp các node lưu trữ nào, dẫn đến lỗ hổng tái sử dụng bằng chứng 
    /// (replay proof) cho một nhóm node khác.
    pub snapshot_id: [u8; 32],
    /// Địa chỉ EVM của Host/Aggregator được cấp quyền nhận phần thưởng nộp bằng chứng cuối cùng (final-submitter reward).
    pub submitter: [u8; 20],
    pub prev_state_root: [u8; 32],
    pub new_state_root: [u8; 32],
    pub num_verified: u32,
}

/// Chiều dài cấu trúc dữ liệu sau khi đóng gói (packed). Hằng số `EngramAttestation.PV_LEN` trong Solidity bắt buộc phải khớp với giá trị này.
pub const PV_PACKED_LEN: usize = 288;

impl PublicValues {
    /// ══════════════════════════════════════════════════════════════════════
    /// CẤU TRÚC ĐÓNG GÓI CHUẨN DÀNH CHO EVM — 288 BYTES, BIG-ENDIAN
    /// ══════════════════════════════════════════════════════════════════════
    ///
    /// ```text
    /// offset  len  field
    /// ------  ---  ------------------------------
    ///      0    8  epoch            (u64, big-endian)
    ///      8   32  batch_root
    ///     40   32  data_root
    ///     72   32  results_root
    ///    104   32  results_data_root
    ///    136   32  storage_vk_digest
    ///    168   32  snapshot_id
    ///    200   20  submitter
    ///    220   32  prev_state_root
    ///    252   32  new_state_root
    ///    284    4  num_verified     (u32, big-endian)
    /// ```
    ///
    /// ⚠ LÝ DO CẦN PHƯƠNG THỨC NÀY (thay vì ủy thác cho `sp1_zkvm::io::commit(&pv)`):
    ///
    /// Hàm `io::commit` sử dụng chuẩn tuần tự hóa `bincode`. Dù `bincode` tạo ra kích thước 
    /// mảng khớp với định dạng độ dài trên contract, nhưng nó mã hóa các biến `u64`/`u32` 
    /// theo chuẩn LITTLE-endian. Trong khi đó, các lệnh Solidity như `uint64(bytes8(...))` 
    /// yêu cầu dữ liệu theo chuẩn BIG-endian. Hậu quả là `epoch` và `num_verified` bị giải mã 
    /// sai lệch, dẫn đến việc hỏng cơ chế kiểm tra đơn điệu (monotonicity check) và cơ chế chống
    /// tấn công gửi lại (anti-replay).
    ///
    /// Lỗi này KHÔNG phát sinh trong `forge test` (do test dùng `abi.encodePacked` mặc định 
    /// đã là big-endian). Nó chỉ lộ diện khi tích hợp bằng chứng thật với contract thật. Do đó, 
    /// cấu trúc byte cần được định nghĩa TƯỜNG MINH tại đây để đồng bộ tính chuẩn xác 
    /// trên toàn hệ thống.
    pub fn to_packed(&self) -> [u8; PV_PACKED_LEN] {
        let mut out = [0u8; PV_PACKED_LEN];
        out[0..8].copy_from_slice(&self.epoch.to_be_bytes());
        out[8..40].copy_from_slice(&self.batch_root);
        out[40..72].copy_from_slice(&self.data_root);
        out[72..104].copy_from_slice(&self.results_root);
        out[104..136].copy_from_slice(&self.results_data_root);
        out[136..168].copy_from_slice(&self.storage_vk_digest);
        out[168..200].copy_from_slice(&self.snapshot_id);
        out[200..220].copy_from_slice(&self.submitter);
        out[220..252].copy_from_slice(&self.prev_state_root);
        out[252..284].copy_from_slice(&self.new_state_root);
        out[284..288].copy_from_slice(&self.num_verified.to_be_bytes());
        out
    }

    /// Quá trình giải mã ngược (nghịch đảo) của `to_packed`. Phương thức này được host sử dụng 
    /// để đọc các giá trị public values đã được guest cam kết (KHÔNG dùng hàm `public_values.read()` 
    /// vì nó mặc định sử dụng bincode).
    pub fn from_packed(b: &[u8]) -> Result<Self, &'static str> {
        if b.len() != PV_PACKED_LEN {
            return Err("Chiều dài public values bắt buộc phải là 288 byte");
        }
        let mut epoch = [0u8; 8];
        let mut batch_root = [0u8; 32];
        let mut data_root = [0u8; 32];
        let mut results_root = [0u8; 32];
        let mut results_data_root = [0u8; 32];
        let mut storage_vk_digest = [0u8; 32];
        let mut snapshot_id = [0u8; 32];
        let mut submitter = [0u8; 20];
        let mut prev_state_root = [0u8; 32];
        let mut new_state_root = [0u8; 32];
        let mut nv = [0u8; 4];
        epoch.copy_from_slice(&b[0..8]);
        batch_root.copy_from_slice(&b[8..40]);
        data_root.copy_from_slice(&b[40..72]);
        results_root.copy_from_slice(&b[72..104]);
        results_data_root.copy_from_slice(&b[104..136]);
        storage_vk_digest.copy_from_slice(&b[136..168]);
        snapshot_id.copy_from_slice(&b[168..200]);
        submitter.copy_from_slice(&b[200..220]);
        prev_state_root.copy_from_slice(&b[220..252]);
        new_state_root.copy_from_slice(&b[252..284]);
        nv.copy_from_slice(&b[284..288]);
        Ok(Self {
            epoch: u64::from_be_bytes(epoch),
            batch_root,
            data_root,
            results_root,
            results_data_root,
            storage_vk_digest,
            snapshot_id,
            submitter,
            prev_state_root,
            new_state_root,
            num_verified: u32::from_be_bytes(nv),
        })
    }
}

/// Đại diện cho bằng chứng (proof) của MỘT node lưu trữ (storage node) trong MỘT epoch.
/// Giá trị `z0` KHÔNG được tuần tự hóa (serialize) — thay vào đó, guest sẽ tái thiết lập nó 
/// dựa trên các trường public values theo định dạng cấu trúc của `EngramStepCircuit`.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ProofBundle {
    pub sector_id: u64,
    pub epoch: u64,
    pub sealed_root: [u8; 32],
    pub beacon: [u8; 32],
    pub replica_id: [u8; 32],
    pub num_steps: u32,
    /// bincode(CompressedSNARK<E1,E2,C,S1,S2>)
    pub proof_bytes: Vec<u8>,
}

/// Bằng chứng Data Availability (DA inclusion proof) cho một lô (batch). 
/// Bằng chứng này được dùng để guest tự tính toán lại `data_root` thay vì phải tin tưởng host.
/// LƯU Ý KỸ THUẬT: Tính năng này hiện chưa được liên kết đầy đủ (tham khảo `guest/src/nmt.rs` 
/// và feature `nmt`).
///
/// Việc bọc trong `Option` giúp tối ưu kích thước bincode (chỉ tiêu tốn thêm 1 byte khi giá trị vắng mặt). 
/// Nhờ đó, lượng cycle đo đạc không bị thay đổi đáng kể. Đây là điểm tích hợp sẵn để chuẩn bị cho 
/// Giai đoạn 3, chưa phải tính năng chính thức ở thời điểm hiện tại.
#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct DaInclusion {
    /// Dữ liệu thô (raw share bytes) được truy xuất từ mạng lưới Celestia qua API `blob.GetAll`.
    pub shares: Vec<Vec<u8>>,
    /// Bằng chứng NMT (Namespace Merkle Tree) dùng cho đoạn dữ liệu share đó qua API `blob.GetProof`.
    pub nmt_siblings: Vec<Vec<u8>>,
    pub start_index: u32,
    pub row_roots: Vec<Vec<u8>>,
    pub col_roots: Vec<Vec<u8>>,
}

/// Cấu trúc tổng hợp đầu vào (input) nạp vào guest cho một lô xác minh (batch).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GuestInput {
    pub epoch: u64,
    /// ⚠ LƯU Ý KHI `da` LÀ `None`: Giá trị này do host CUNG CẤP. Guest sẽ sao chép 
    /// trực tiếp nó ra public values mà không tiến hành kiểm chứng chéo. 
    /// Ở chế độ này, hệ thống sẽ KHÔNG thể ràng buộc chặt chẽ tính hợp lệ 
    /// của dữ liệu trên Celestia. Dù mọi chỉ số đo lường hiệu năng vẫn hợp lệ, nhưng tính 
    /// xác thực từ đầu đến cuối (end-to-end soundness) sẽ không được bảo đảm. 
    /// Đây là hiện trạng của phiên bản nguyên mẫu (prototype) này.
    pub data_root: [u8; 32],
    /// ★ QUAN TRỌNG: Đã loại bỏ trường `results_root` khỏi input của guest. Guest sẽ 
    /// tự động tính toán giá trị này từ kết quả xác minh và host không còn được truyền nó vào.
    ///
    /// Tuy nhiên, `results_data_root` vẫn sẽ do host khai báo vì nó đóng vai trò 
    /// con trỏ vị trí (pointer) đến nơi lưu trữ danh sách quyết toán, chứ không tác động 
    /// đến nội dung kết quả thực tế.
    #[serde(default)]
    pub results_data_root: [u8; 32],
    /// ★ Định danh bản ghi trạng thái (snapshot ID) của epoch, đóng vai trò chốt chặn 
    /// danh sách các node lưu trữ (storage nodes) hợp lệ cho epoch tương ứng.
    #[serde(default)]
    pub snapshot_id: [u8; 32],
    #[serde(default)]
    pub submitter: [u8; 20],
    pub prev_state_root: [u8; 32],
    /// Dữ liệu khóa xác minh `bincode(VerifierKey<E1,E2,C,S1,S2>)` — áp dụng đồng bộ cho MỌI bundle trong batch.
    pub vk_bytes: Vec<u8>,
    pub bundles: Vec<ProofBundle>,
    /// Khi mang giá trị `Some` → guest sẽ TỰ ĐỘNG TÍNH TOÁN `data_root` từ bằng chứng NMT 
    /// và bỏ qua trường `data_root` được cung cấp ở bên trên.
    #[serde(default)]
    pub da: Option<DaInclusion>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> PublicValues {
        PublicValues {
            epoch: 1,
            batch_root: [0x22; 32],
            data_root: [0x11; 32],
            results_root: [0x44; 32],
            results_data_root: [0x55; 32],
            storage_vk_digest: [0x33; 32],
            snapshot_id: [0x66; 32],
            submitter: [0x77; 20],
            prev_state_root: [0u8; 32],
            new_state_root: [0xAB; 32],
            num_verified: 7,
        }
    }

    #[test]
    fn packed_len_matches_solidity_constant() {
        assert_eq!(sample().to_packed().len(), 288);
    }

    /// Unit test này được thiết kế ĐẶC BIỆT ĐỂ THẤT BẠI (fail) nếu định dạng dữ liệu 
    /// vô tình bị đổi sang cấu trúc little-endian. Nó đối xứng với hàm kiểm tra `test_PvIsBigEndian` 
    /// trong môi trường Solidity, đảm bảo cả hai hệ thống cùng chia sẻ một ràng buộc bất biến (invariant).
    #[test]
    fn integers_are_big_endian() {
        let p = sample().to_packed();
        assert_eq!(p[0], 0, "byte 0 của epoch phải là MSB");
        assert_eq!(p[7], 1, "byte 7 của epoch phải là LSB");
        assert_eq!(p[284], 0, "byte 0 của num_verified phải là MSB");
        assert_eq!(p[287], 7, "byte 3 của num_verified phải là LSB");
    }

    /// ★ Kiểm tra việc cấp phát bộ nhớ của `snapshot_id`: xác thực trường dữ liệu 
    /// nằm đúng offset và không chiếm đè vào phần không gian bộ nhớ của `submitter`.
    #[test]
    fn snapshot_id_occupies_168_to_200() {
        let p = sample().to_packed();
        assert_eq!(&p[168..200], &[0x66u8; 32], "snapshot_id sai offset");
        assert_eq!(&p[200..220], &[0x77u8; 20], "submitter bị lấn");
    }

    #[test]
    fn roundtrip() {
        let a = sample();
        let b = PublicValues::from_packed(&a.to_packed()).unwrap();
        assert_eq!(a, b);
    }

    #[test]
    fn rejects_wrong_length() {
        assert!(PublicValues::from_packed(&[0u8; 255]).is_err());
        assert!(PublicValues::from_packed(&[0u8; 257]).is_err());
    }
}
