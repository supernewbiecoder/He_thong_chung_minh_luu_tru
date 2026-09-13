// Build guest ELF (../guest) mỗi lần build host, giống sp1_verify/host/build.rs.
// Nếu guest không compile cho riscv32im-succinct-zkvm-elf thì FAIL Ở ĐÂY.
fn main() {
    sp1_build::build_program("../guest");
}
