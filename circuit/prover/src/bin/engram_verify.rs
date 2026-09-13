//! `engram_verify` — xác minh một bằng chứng lưu trữ THẬT.
//!
//! Worker gọi binary này qua `provider.rust_bridge`. Đọc đúng ba file mà
//! `engram_prove` ghi ra, verify, in một dòng JSON.
//!
//! Đây là thứ biến phán quyết PASS/FAIL thành kết luận về MẬT MÃ chứ không phải
//! về một cờ: nếu nút đục lỗ sector thì `sealed_root` đổi, đường Merkle không
//! khớp, và verify trả false.

use nova_snark::nova::CompressedSNARK;
use prover::{EngramStepCircuit, EngramVerifierKey, G1, G2, SpartanPrimary, SpartanSecondary};
use std::path::PathBuf;
use std::time::Instant;

type Proof = CompressedSNARK<G1, G2, EngramStepCircuit, SpartanPrimary, SpartanSecondary>;

fn arg(name: &str, default: &str) -> String {
    let args: Vec<String> = std::env::args().collect();
    for w in args.windows(2) {
        if w[0] == format!("--{name}") {
            return w[1].clone();
        }
    }
    default.to_string()
}

fn main() {
    let dir = PathBuf::from(arg("dir", "/tmp/engram-proof"));
    let steps: usize = arg("steps", "3").parse().expect("--steps");

    let proof_b = std::fs::read(dir.join("proof.bin")).expect("đọc proof.bin");
    let vk_b = std::fs::read(dir.join("vk.bin")).expect("đọc vk.bin");
    let z0_b = std::fs::read(dir.join("z0.bin")).expect("đọc z0.bin");

    let proof: Proof = match bincode::deserialize(&proof_b) {
        Ok(p) => p,
        Err(e) => {
            // Blob hỏng hoặc bị thay — KHÔNG panic, vì dữ liệu đến từ DA công
            // khai và một ngoại lệ trên đường nóng là một kiểu DoS.
            println!("{{\"verify_ok\":false,\"reason\":\"proof hong: {e}\"}}");
            return;
        }
    };
    let vk: EngramVerifierKey = bincode::deserialize(&vk_b).expect("vk hỏng");
    let z0: Vec<_> = bincode::deserialize(&z0_b).expect("z0 hỏng");

    let t = Instant::now();
    let ok = proof.verify(&vk, steps, &z0).is_ok();
    println!(
        "{{\"verify_ok\":{},\"verify_ms\":{:.3},\"proof_bytes\":{}}}",
        ok,
        t.elapsed().as_secs_f64() * 1000.0,
        proof_b.len()
    );
    if !ok {
        std::process::exit(1);
    }
}
