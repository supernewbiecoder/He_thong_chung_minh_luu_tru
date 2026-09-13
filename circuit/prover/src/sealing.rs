//! Module Sealing (Niêm phong)
//!
//! Module này chịu trách nhiệm thực hiện quá trình "sealing" (niêm phong) một sector dữ liệu.
//! Chức năng chính bao gồm việc chuyển đổi các chunk dữ liệu dạng byte sang phần tử trường (`Fr`),
//! tính toán các replica chunk `R_i` và trạng thái `S_i`, sau đó lưu trữ vào `ProverStorage`
//! và xây dựng cây Merkle (Merkle tree) từ các cặp `(R_i, S_i)`.
//! Thiết kế hiện tại áp dụng cơ chế sealing theo luồng (streaming), tức là đọc file theo nhu cầu (on-demand)
//! thay vì lưu giữ toàn bộ dữ liệu thô (raw chunks) trong bộ nhớ RAM, giúp tối ưu hóa tài nguyên.
//!
use core_primitives::config::EngramConfig;
use core_primitives::poseidon2::hash_2;
use core_primitives::merkle_tree::MerkleTree;
use core_primitives::Fr;
use crate::storage::ProverStorage;
use crate::benchmark::{elapsed_ms_f64, PeakMemoryTracker, SealingMetrics};
use std::io::{BufReader, Read};
use std::path::Path;
use std::time::Instant;

/// Chuyển đổi một chuỗi byte (slice) thành một phần tử trường `Fr`.
///
/// Cách thức hoạt động: Đầu vào được chia nhỏ thành các đoạn 31-byte.
/// Mỗi đoạn sau đó được chuyển đổi thành phần tử `Fr` và được gộp (fold)
/// vào một biến tích lũy (accumulator) thông qua hàm `hash_2`.
/// Phương pháp này đảm bảo rằng mọi bit của đầu vào đều có ảnh hưởng đến kết quả cuối cùng.
use core_primitives::chunking::bytes_to_fr as chunk_to_fr;

/// Hàm hỗ trợ: Thực hiện băm (hash) gộp 4 phần tử thông qua việc gọi hàm `hash_2` hai lần.
/// Hàm này được sử dụng như một tiện ích khi cần kết hợp (trộn) 4 đầu vào khác nhau thành một giá trị duy nhất.
fn poseidon2_hash_4(a: Fr, b: Fr, c: Fr, d: Fr) -> Fr {
    hash_2(hash_2(a, b), hash_2(c, d))
}

pub struct Sealer {
    config: EngramConfig,
}

impl Sealer {
    pub fn new(config: EngramConfig) -> Self {
        Self { config }
    }

    /// Thực hiện niêm phong (seal) một sector trực tiếp từ TỆP - không tải toàn bộ dữ liệu thô vào RAM.
    ///
    /// # Mức tiêu thụ bộ nhớ (RAM Profile)
    /// - BufReader: Bộ đệm dung lượng `chunk_size * 256` bytes (khoảng 1MB cho chunk kích thước 4KB).
    /// - sealed_pairs: `num_chunks × 64` bytes (khoảng 512MB đối với sector 32GB).
    /// - states và replicas: `num_chunks × 64` bytes (khoảng 512MB).
    /// - Cây Merkle (Merkle tree): khoảng 512MB.
    /// - Tổng cộng: Khoảng 1.5GB, tối ưu đáng kể so với mức 64GB của phiên bản trước đó.
    ///
    /// # Thời gian niêm phong (Sealing Time)
    /// Với sector 32GB (tương đương 8 triệu chunks), sử dụng 2 phép băm Poseidon2 sẽ mất khoảng 27 phút trên đơn luồng (single-thread).
    /// Đây là thời gian thực thi tiêu chuẩn của thuật toán PoSt, không phải là lỗi hiệu năng.
    /// Sự phụ thuộc tuần tự của trạng thái `S_i` làm hạn chế khả năng song song hóa hoàn toàn.
    pub fn seal_sector_streaming(
        &self,
        replica_id: Fr,
        raw_data_path: &Path,
        storage: &mut ProverStorage,
    ) -> SealingMetrics {
        const RAM_SAMPLE_EVERY: usize = 256;
        // Ghi lại trạng thái của bộ đếm I/O trước khi bắt đầu quá trình niêm phong để tính toán mức chênh lệch (delta) của lần gọi hàm này
        let io_ns_before = crate::benchmark::io_get_ns_total();
        let io_count_before = crate::benchmark::io_get_count();
        let chunk_size  = self.config.chunk_size_bytes;
        let num_chunks  = self.config.sector_size_bytes / chunk_size;
        let buf_chunks  = 256usize;           // Số lượng chunks đọc trong một lần (256 chunks = 1MB bộ đệm)
        let buf_size    = chunk_size * buf_chunks;

        *storage = ProverStorage::with_capacity(num_chunks, chunk_size);
        storage.set_raw_data_path(raw_data_path.to_path_buf());

        let file   = std::fs::File::open(raw_data_path)
            .unwrap_or_else(|e| panic!("Không mở được {}: {}", raw_data_path.display(), e));
        let mut reader  = BufReader::with_capacity(buf_size, file);

        let mut s_prev       = replica_id;
        let mut sealed_pairs = Vec::with_capacity(num_chunks);
        let mut metrics      = SealingMetrics::default();
        let mut peak         = PeakMemoryTracker::new();
        let mut chunk_buf    = vec![0u8; chunk_size];

        storage.insert_state(0, s_prev);

        for i in 1..=num_chunks {
            // ── Đọc chunk từ tệp (chỉ truyền luồng, không lưu trữ tạm) ─────────────
            let absorb_start = Instant::now();
            // Xử lý sự kiện kết thúc tệp (EOF) một cách an toàn bằng cách đệm các byte 0 (zero-padding)
            let bytes_read = fill_chunk(&mut reader, &mut chunk_buf);
            if bytes_read < chunk_size {
                chunk_buf[bytes_read..].fill(0);
            }
            metrics.c_chunk_absorb_4kb_ms += elapsed_ms_f64(absorb_start);
            // Cập nhật bộ đếm I/O toàn cục (mỗi lần đọc chunk được tính là một thao tác I/O)
            let ns = absorb_start.elapsed().as_nanos() as u64;
            crate::benchmark::io_add_ns(ns);
            crate::benchmark::io_inc_count(1);

            // ── Quá trình niêm phong (Sealing) ───────────────────────────────────────────
            let hash_start = Instant::now();
            let d_i = chunk_to_fr(&chunk_buf);
            let r_i = poseidon2_hash_4(d_i, s_prev, Fr::from(i as u64), replica_id);
            metrics.c_hash_poseidon2_ms += elapsed_ms_f64(hash_start);

            let s_i = hash_2(s_prev, r_i);

            // ── Lưu trữ dữ liệu đã niêm phong (không lưu trữ chunk dữ liệu thô) ─────────
            storage.insert_replica(i, r_i);
            storage.insert_state(i, s_i);
            sealed_pairs.push((r_i, s_i));
            s_prev = s_i;

            if i % RAM_SAMPLE_EVERY == 0 || i == num_chunks {
                peak.sample();
            }
        }

        let merkle_start = Instant::now();
        let tree = MerkleTree::build(&sealed_pairs);
        metrics.c_merkle_build_ms = elapsed_ms_f64(merkle_start);
        storage.merkle_tree = Some(tree);

        metrics.ram_peak_kib = peak.peak_delta_kib();
        // Tính toán mức chênh lệch I/O (delta) sinh ra trong quá trình gọi hàm niêm phong này
        let io_ns_after = crate::benchmark::io_get_ns_total();
        let io_count_after = crate::benchmark::io_get_count();
        metrics.io_read_ms = (io_ns_after.saturating_sub(io_ns_before) as f64) / 1_000_000.0;
        metrics.io_read_count = io_count_after.saturating_sub(io_count_before);
        metrics
    }
}

/// Đọc chính xác một số lượng byte bằng `buf.len()` vào bộ đệm `buf` từ đối tượng `reader`.
/// Trả về số lượng byte thực tế đã được đọc (có thể nhỏ hơn kích thước bộ đệm nếu gặp sự kiện kết thúc tệp EOF).
fn fill_chunk<R: Read>(reader: &mut R, buf: &mut [u8]) -> usize {
    let mut total = 0;
    while total < buf.len() {
        match reader.read(&mut buf[total..]) {
            Ok(0)   => break,
            Ok(n)   => total += n,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_)  => break,
        }
    }
    total
}
