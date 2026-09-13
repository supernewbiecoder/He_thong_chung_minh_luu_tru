//! `engram_prove` — sinh bằng chứng lưu trữ THẬT cho một hợp đồng, ghi ra file.
//!
//! Đây là cầu giữa tầng Python (điều phối, DA, worker, aggregator) và mạch Rust.
//! Python gọi binary này qua `provider.rust_bridge`, nhận lại:
//!
//!     <out>/proof.bin      bằng chứng Spartan nén — ĐÚNG byte sẽ lên Celestia
//!     <out>/vk.bin         khoá xác minh, để `engram_verify` dùng lại
//!     <out>/z0.bin         trạng thái đầu, cần cho verify
//!     stdout               một dòng JSON gồm mọi số đo
//!
//! ── VÌ SAO GHI RA FILE THAY VÌ IN RA MÀN HÌNH ───────────────────────────────
//!
//! Bằng chứng là thứ phải ĐI LÊN DA, nên nó phải tồn tại dưới dạng byte mà tầng
//! trên cầm được. Bản `smoke_bn254` chỉ in kích thước rồi vứt — đủ cho một bài
//! kiểm khói, không đủ cho một hệ chạy thật.
//!
//! ── SỐ ĐO LÀ ĐO, KHÔNG PHẢI MÔ HÌNH ─────────────────────────────────────────
//!
//! Mọi trường trong JSON đều lấy từ `Instant::now()` của lần chạy này, trên máy
//! này. Không có hằng số nào được điền sẵn. Nếu máy chậm thì số lớn, và đó là
//! thông tin đúng chứ không phải lỗi.
//!
//! ── LƯU Ý VỀ THUẬT TOÁN NIÊM PHONG ──────────────────────────────────────────
//!
//! Mạch này hiện thực Thuật toán 1c: `R_i = H4(D_i, S_{i-1}, i, replica_id)`,
//! KHÔNG có fan-in. Bản SeqWide có fan-in φ=6 nằm ở `provider/sealing.py` và
//! hiện là THIẾT KẾ + MÔ PHỎNG, chưa vào mạch. Đưa fan-in vào mạch đòi thêm 5
//! đường Merkle cho 5 trạng thái fan-in, nên là một lần sửa mạch thật chứ không
//! phải vá nhỏ. Xem `HE_THONG_THAT.md`.

use core_primitives::chunking::{bytes_to_fr, bytes_to_limbs as chunk_to_limbs};
use core_primitives::config::EngramConfig;
use core_primitives::poseidon2::hash_2;
use core_primitives::Fr;
use ff::{Field, PrimeField};
use prover::{EngramStepCircuit, ProverStorage, ProvingPipeline, Sealer};
use std::io::Write;
use std::path::PathBuf;
use std::time::Instant;

fn poseidon2_chain(values: &[Fr]) -> Fr {
    let mut acc = Fr::ZERO;
    for v in values {
        acc = hash_2(acc, *v);
    }
    acc
}

/// Giống `derive_challenge_index` trong simulator_runner — host và mạch phải
/// dẫn xuất cùng một chỉ số, nếu không thì verify từ chối.
fn derive_challenge_index(
    beacon: Fr,
    sector_id: u64,
    epoch: usize,
    challenge_no: usize,
    num_chunks: usize,
) -> usize {
    let seed = poseidon2_chain(&[
        beacon,
        Fr::from(sector_id),
        Fr::from(epoch as u64),
        Fr::from(challenge_no as u64),
    ]);
    let seed_bytes = seed.to_repr();
    let j = u64::from_le_bytes(seed_bytes.as_ref()[0..8].try_into().unwrap());
    (j as usize % num_chunks).saturating_add(1)
}

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
    // ── Tham số: KHÔNG ghim cứng, để người chạy tự chọn quy mô ──────────────
    let sector_path = PathBuf::from(arg("sector", ""));
    let out_dir = PathBuf::from(arg("out", "/tmp/engram-proof"));
    let n_chunks: usize = arg("chunks", "16").parse().expect("--chunks");
    let chunk_size: usize = arg("chunk-size", "4096").parse().expect("--chunk-size");
    let tree_height: usize = arg("tree-height", "4").parse().expect("--tree-height");
    let n_challenges: usize = arg("challenges", "3").parse().expect("--challenges");
    let sector_id: u64 = arg("sector-id", "7").parse().expect("--sector-id");
    let epoch: usize = arg("epoch", "0").parse().expect("--epoch");
    let replica_seed = arg("replica", "engram-replica-id");
    let beacon_seed = arg("beacon", "engram-beacon-000");

    if sector_path.as_os_str().is_empty() {
        eprintln!("thiếu --sector <đường dẫn file dữ liệu thô>");
        std::process::exit(2);
    }
    std::fs::create_dir_all(&out_dir).expect("tạo thư mục đầu ra");

    let config = EngramConfig {
        sector_size_bytes: n_chunks * chunk_size,
        chunk_size_bytes: chunk_size,
        tree_height,
        challenges_per_epoch: n_challenges,
        epochs_per_window: 1,
    };

    // ── 1. NIÊM PHONG, đọc theo luồng từ file thật ──────────────────────────
    let replica_id = bytes_to_fr(replica_seed.as_bytes());
    let sealer = Sealer::new(config.clone());
    let mut storage = ProverStorage::new();
    let t_seal = Instant::now();
    let _m = sealer.seal_sector_streaming(replica_id, &sector_path, &mut storage);
    let seal_ms = t_seal.elapsed().as_secs_f64() * 1000.0;
    let sealed_root = storage.merkle_tree.as_ref().expect("merkle tree").root;

    // ── 2. DẪN XUẤT THÁCH THỨC từ beacon ───────────────────────────────────
    let beacon = bytes_to_fr(beacon_seed.as_bytes());
    let mut challenges = Vec::new();
    let mut j_list = Vec::new();
    for c in 1..=n_challenges {
        let j_i = derive_challenge_index(beacon, sector_id, epoch, c, n_chunks);
        j_list.push(j_i);
        let raw_chunk = storage.get_raw_chunk(j_i).expect("đọc chunk thô");
        challenges.push(EngramStepCircuit {
            epoch,
            sector_id: Fr::from(sector_id),
            sealed_root,
            beacon,
            j_i,
            s_ji_minus_1: *storage.get_state(j_i - 1).expect("S_{j-1}"),
            s_ji: *storage.get_state(j_i).expect("S_j"),
            replica_id,
            path_ji_siblings: storage
                .merkle_tree
                .as_ref()
                .unwrap()
                .generate_proof(j_i - 1)
                .siblings,
            path_ji_indices: storage
                .merkle_tree
                .as_ref()
                .unwrap()
                .generate_proof(j_i - 1)
                .path_indices,
            tree_height,
            chunk_limbs: chunk_to_limbs(&raw_chunk),
            chunk_size_bytes: chunk_size,
        });
    }

    // ── 3. NOVA setup → fold → nén Spartan ─────────────────────────────────
    let t_setup = Instant::now();
    let (pipeline, _setup_m) = ProvingPipeline::setup(challenges[0].clone());
    let setup_ms = t_setup.elapsed().as_secs_f64() * 1000.0;

    let num_steps = challenges.len();
    let t_prove = Instant::now();
    let (proof, z0, prove_m) = pipeline.prove_epoch(challenges);
    let prove_ms = t_prove.elapsed().as_secs_f64() * 1000.0;

    // ── 4. VERIFY ngay tại chỗ ─────────────────────────────────────────────
    let t_verify = Instant::now();
    let verify_ok = proof.verify(&pipeline.vk, num_steps, &z0).is_ok();
    let verify_ms = t_verify.elapsed().as_secs_f64() * 1000.0;

    // ── 5. GHI RA FILE để tầng trên cầm được ───────────────────────────────
    let proof_bytes = bincode::serialize(&proof).expect("serialize proof");
    std::fs::write(out_dir.join("proof.bin"), &proof_bytes).expect("ghi proof.bin");
    std::fs::write(
        out_dir.join("vk.bin"),
        bincode::serialize(&pipeline.vk).expect("serialize vk"),
    )
    .expect("ghi vk.bin");
    std::fs::write(
        out_dir.join("z0.bin"),
        bincode::serialize(&z0).expect("serialize z0"),
    )
    .expect("ghi z0.bin");

    // ── 6. MỘT DÒNG JSON, mọi số đều ĐO ────────────────────────────────────
    let json = format!(
        concat!(
            "{{\"ok\":{},\"sealed_root\":\"{:?}\",\"n_chunks\":{},\"chunk_size\":{},",
            "\"challenges\":{:?},\"proof_bytes\":{},\"proof_bytes_reported\":{},",
            "\"seal_ms\":{:.3},\"setup_ms\":{:.3},\"prove_ms\":{:.3},\"verify_ms\":{:.3},",
            "\"verify_ok\":{},\"out_dir\":\"{}\"}}"
        ),
        verify_ok,
        sealed_root,
        n_chunks,
        chunk_size,
        j_list,
        proof_bytes.len(),
        prove_m.compressed_proof_size_bytes,
        seal_ms,
        setup_ms,
        prove_ms,
        verify_ms,
        verify_ok,
        out_dir.display()
    );
    let mut out = std::io::stdout();
    writeln!(out, "{json}").unwrap();

    if !verify_ok {
        std::process::exit(1);
    }
}
