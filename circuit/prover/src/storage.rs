//! Lưu trữ của Prover (Prover storage)
//!
//! Hệ thống lưu trữ dựa trên tệp tin dành cho Prover:
//! - Lưu trữ `states` (trạng thái) và `replicas` (bản sao) trong RAM để đảm bảo tốc độ truy cập cao trong quá trình chứng minh (proving).
//! - `raw_data` (dữ liệu thô) không được lưu trữ trong RAM; thay vào đó, hàm `get_raw_chunk()` sẽ đọc dữ liệu theo yêu cầu (on-demand) từ đường dẫn tệp được chỉ định.
//! - Cung cấp hỗ trợ mô phỏng các kịch bản tấn công thông qua thuộc tính `dropped_raw_indices` và các hàm có tiền tố `attack_*`.
//!
use core_primitives::Fr;
use core_primitives::merkle_tree::MerkleTree;
use std::collections::HashSet;
use std::io::{Read, Seek, SeekFrom};
use std::path::PathBuf;

/// Cấu trúc `ProverStorage` — Hệ thống lưu trữ dữ liệu chunk thô (raw chunk data) dựa trên tệp tin.
///
/// # Những thay đổi so với phiên bản trước
/// Ở phiên bản trước, toàn bộ `raw_chunks`: `Vec<Option<Vec<u8>>>` được tải và lưu trong RAM.
/// Điều này dẫn đến việc một sector kích thước 32GB (8 triệu chunks × 4KB) sẽ tiêu tốn 32GB RAM chỉ để lưu dữ liệu thô.
/// Tính thêm 32GB `raw_sector_data` được tải trước đó, tổng dung lượng RAM cần thiết lên đến 64GB — một mức tiêu thụ không thể chấp nhận được.
///
/// # Thiết kế mới
/// - `raw_chunks` KHÔNG còn được lưu trữ trong RAM. Dữ liệu sẽ được đọc từ tệp tin theo yêu cầu (on-demand) khi cần thiết.
/// - `dropped_raw_indices`: `HashSet<usize>` được sử dụng để đánh dấu các chunk đã bị "xóa" (nhằm phục vụ việc mô phỏng tấn công).
/// - `states` và `replicas` tiếp tục được lưu trong RAM (tiêu tốn khoảng 512MB cho sector 32GB) — đây là yêu cầu bắt buộc để đảm bảo hiệu suất.
/// - Cấu trúc dữ liệu Merkle tree cũng được giữ trong RAM (khoảng 512MB) — bắt buộc.
///
/// # Mức sử dụng RAM sau khi tối ưu
/// Đối với sector 32GB: `states` (256MB) + `replicas` (256MB) + `merkle tree` (512MB) ≈ Tổng cộng khoảng 1.0GB.
#[derive(Default, Clone)]
pub struct ProverStorage {
    /// Đường dẫn đến tệp tin chứa dữ liệu thô gốc — được dùng để đọc on-demand, không tải toàn bộ vào RAM.
    pub raw_data_path: Option<PathBuf>,
    /// Kích thước của mỗi chunk (tính bằng byte), cần thiết để tính toán độ dời (offset) khi đọc tệp.
    pub chunk_size: usize,
    /// Tập hợp chứa các chỉ số (index) của các chunk bị "loại bỏ" (nhằm phục vụ việc mô phỏng tấn công).
    /// Hàm `has_raw_chunk(i)` sẽ trả về `false` nếu `i` nằm trong `dropped_raw_indices`.
    pub dropped_raw_indices: HashSet<usize>,
    /// Mảng trạng thái `states[i] = S_i` (chỉ số bắt đầu từ 0: `states[0]` là `replica_id`, `states[i]` là `S_i` sau chunk thứ `i`).
    pub states: Vec<Option<Fr>>,
    /// Mảng bản sao `replicas[i] = R_i` (chỉ số bắt đầu từ 1, bỏ qua phần tử ở chỉ số 0).
    pub replicas: Vec<Option<Fr>>,
    pub merkle_tree: Option<MerkleTree>,
    pub num_chunks: usize,
}

impl ProverStorage {
    pub fn new() -> Self {
        Self::default()
    }

    /// Khởi tạo cấu trúc lưu trữ với sức chứa (capacity) được xác định trước.
    /// Tham số `chunk_size` là bắt buộc để tính toán độ dời (offset) khi tiến hành đọc tệp tin.
    pub fn with_capacity(num_chunks: usize, chunk_size: usize) -> Self {
        Self {
            raw_data_path: None,
            chunk_size,
            dropped_raw_indices: HashSet::new(),
            states:   vec![None; num_chunks + 1],
            replicas: vec![None; num_chunks + 1],
            merkle_tree: None,
            num_chunks,
        }
    }

    /// Thiết lập đường dẫn đến tệp tin dữ liệu thô. Hàm này được gọi sau khi quá trình niêm phong (sealing) hoàn tất.
    pub fn set_raw_data_path(&mut self, path: PathBuf) {
        self.raw_data_path = Some(path);
    }

    // ── Quản lý Trạng thái (State) ────────────────────────────────────────────────────────

    #[inline]
    pub fn insert_state(&mut self, i: usize, s: Fr) {
        if i < self.states.len() { self.states[i] = Some(s); }
    }

    #[inline]
    pub fn get_state(&self, i: usize) -> Option<&Fr> {
        self.states.get(i)?.as_ref()
    }

    // ── Quản lý Bản sao (Replica) ─────────────────────────────────────────────────────────

    #[inline]
    pub fn insert_replica(&mut self, i: usize, r: Fr) {
        if i < self.replicas.len() { self.replicas[i] = Some(r); }
    }

    #[inline]
    pub fn get_replica(&self, i: usize) -> Option<&Fr> {
        self.replicas.get(i)?.as_ref()
    }

    // ── Quản lý Dữ liệu thô (Dựa trên tệp tin) ──────────────────────────────────────────

    /// Kiểm tra xem chunk thứ `i` có tồn tại hay không.
    /// Trả về `false` nếu chunk này đã bị loại bỏ (trong kịch bản tấn công) hoặc tệp tin dữ liệu không tồn tại.
    #[inline]
    pub fn has_raw_chunk(&self, i: usize) -> bool {
        if self.dropped_raw_indices.contains(&i) { return false; }
        i >= 1 && i <= self.num_chunks && self.raw_data_path.is_some()
    }

    /// Đọc chunk thứ `i` từ tệp tin (thực hiện theo yêu cầu on-demand, độ phức tạp bộ nhớ là O(1)).
    /// Di chuyển con trỏ đọc (seek) đến vị trí `offset = (i - 1) * chunk_size` và đọc một lượng bằng `chunk_size` byte.
    pub fn get_raw_chunk(&self, i: usize) -> Option<Vec<u8>> {
        if self.dropped_raw_indices.contains(&i) { return None; }
        let path = self.raw_data_path.as_ref()?;
        let offset = ((i - 1) as u64) * (self.chunk_size as u64);
        let start = std::time::Instant::now();
        let mut file = std::fs::File::open(path).ok()?;
        file.seek(SeekFrom::Start(offset)).ok()?;
        let mut buf = vec![0u8; self.chunk_size];
        file.read_exact(&mut buf).ok()?;
        // Ghi lại số liệu thống kê liên quan đến I/O (tính bằng nano giây).
        let ns = start.elapsed().as_nanos() as u64;
        crate::benchmark::io_add_ns(ns);
        crate::benchmark::io_inc_count(1);
        Some(buf)
    }

    // ── Mô phỏng Kịch bản Tấn công ──────────────────────────────────────────────────────────

    /// Tạo một chuỗi số giả ngẫu nhiên dựa trên hạt giống (seed) đầu vào (sử dụng thuật toán LCG tất định).
    fn lcg_next(state: &mut u64) -> u64 {
        *state = state.wrapping_mul(6364136223846793005)
                      .wrapping_add(1442695040888963407);
        *state
    }

    /// Kịch bản tấn công 1: Loại bỏ ngẫu nhiên một tỷ lệ `drop_pct`% các chunk thô.
    /// Quá trình này chỉ đánh dấu các chỉ số vào `dropped_raw_indices` thay vì thực sự xóa phần tử trong `Vec`.
    pub fn attack_drop_raw_chunks_random_pct(&mut self, drop_pct: f64, seed: u64) -> Vec<usize> {
        if self.num_chunks == 0 || drop_pct <= 0.0 { return Vec::new(); }
        let drop_count = ((self.num_chunks as f64) * drop_pct / 100.0).round() as usize;
        let drop_count = drop_count.min(self.num_chunks);

        let mut keys: Vec<usize> = (1..=self.num_chunks)
            .filter(|i| !self.dropped_raw_indices.contains(i))
            .collect();

        let mut rng = seed.wrapping_add(0x9E3779B97F4A7C15);
        for i in (1..keys.len()).rev() {
            let r = (Self::lcg_next(&mut rng) as usize) % (i + 1);
            keys.swap(i, r);
        }

        let removed: Vec<usize> = keys.into_iter().take(drop_count).collect();
        for &k in &removed { self.dropped_raw_indices.insert(k); }
        let mut out = removed;
        out.sort_unstable();
        out
    }

    /// Kịch bản tấn công 2: Loại bỏ chính xác các chunk tại các chỉ số (index) được chỉ định.
    pub fn attack_drop_raw_chunks_at(&mut self, indices: &[usize]) -> Vec<usize> {
        let mut removed = Vec::new();
        for &idx in indices {
            if idx >= 1 && idx <= self.num_chunks {
                self.dropped_raw_indices.insert(idx);
                removed.push(idx);
            }
        }
        removed
    }

    /// Kịch bản tấn công 3: Loại bỏ trạng thái `S_{j_i-1}` tại các vị trí truy vấn (challenge).
    pub fn attack_drop_states_at(&mut self, state_indices: &[usize]) -> Vec<usize> {
        let mut removed = Vec::new();
        for &idx in state_indices {
            if idx < self.states.len() {
                if self.states[idx].take().is_some() { removed.push(idx); }
            }
        }
        removed
    }

    /// Tạo một bản sao của hệ thống lưu trữ để thực thi độc lập từng kịch bản tấn công.
    pub fn clone_for_attack(&self) -> Self {
        Self {
            raw_data_path: self.raw_data_path.clone(),
            chunk_size: self.chunk_size,
            dropped_raw_indices: HashSet::new(), // Xóa các bản ghi đã loại bỏ trước đó để bắt đầu kịch bản mới.
            states:   self.states.clone(),
            replicas: self.replicas.clone(),
            merkle_tree: self.merkle_tree.clone(),
            num_chunks: self.num_chunks,
        }
    }
}
