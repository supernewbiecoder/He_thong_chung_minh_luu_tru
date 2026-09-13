// Tự động build guest ELF (../guest) mỗi khi build host, và đặt ELF vào chỗ
// include_elf!("engram-guest") biết tìm. Nhờ vậy không cần chạy cargo prove build tay,
// và không lo sai đường dẫn ELF giữa các version SP1.
fn main() {
    sp1_build::build_program("../guest");
}
