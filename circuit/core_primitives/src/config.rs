// Tệp này chứa các cấu hình mặc định cho Engram, có khả năng mở rộng trong tương lai.

#[derive(Clone, Debug)]
pub struct EngramConfig {
    pub sector_size_bytes: usize,
    pub chunk_size_bytes: usize,
    pub tree_height: usize,
    pub challenges_per_epoch: usize,
    pub epochs_per_window: usize,
}

impl EngramConfig {
    /// Cấu hình dùng để chạy mô phỏng và kiểm thử các kịch bản tấn công (tối ưu hóa cho tốc độ và dung lượng nhẹ).
    pub fn mock_dev() -> Self {
        Self {
            sector_size_bytes: 1 * 1024 * 1024 * 1024, // Tự động thiết lập dung lượng sector là 1GB.
            chunk_size_bytes: 4096,                // Kích thước mỗi chunk là 4KB (tương đương 1 shard mỗi chunk).
            tree_height: 18,                       // Tự động thiết lập chiều cao cây Merkle là 18.
            challenges_per_epoch: 50,
            epochs_per_window: 5, // Số epoch trong mỗi cửa sổ thời gian (dành cho các mô phỏng trong tương lai).
        }
    }

    /// Cấu hình môi trường thực tế dựa trên báo cáo (dùng để đo lường hiệu suất thực tế).
    pub fn production() -> Self {
        Self {
            sector_size_bytes: 32 * 1024 * 1024 * 1024, // Dung lượng sector là 32GB.
            chunk_size_bytes: 4096,
            tree_height: 23,                            // Chiều cao cây Merkle là 23 (2^23 lá tương đương 32GB).
            challenges_per_epoch: 100,
            epochs_per_window: 48,
        }
    }
}
