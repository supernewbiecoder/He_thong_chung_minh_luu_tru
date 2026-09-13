//! Smoke test end-to-end cho migration BN254:
//! seal sector nhỏ (64KB) → derive 3 challenges → Nova fold → CompressedSNARK
//! (HyperKZG trên BN254 + IPA trên Grumpkin) → verify.
//!
//! Logic derive challenge / build witness sao chép đúng từ simulator_runner/main.rs
//! để đảm bảo host ↔ circuit nhất quán.

use core_primitives::config::EngramConfig;
use core_primitives::chunking::{bytes_to_fr, bytes_to_limbs as chunk_to_limbs};
use core_primitives::poseidon2::hash_2;
use core_primitives::Fr;
use ff::{Field, PrimeField};
use prover::{EngramStepCircuit, ProverStorage, ProvingPipeline, Sealer};
use std::io::Write;
use std::time::Instant;

fn string_to_fr(s: &str) -> Fr {
    bytes_to_fr(s.as_bytes())
}

fn poseidon2_chain(values: &[Fr]) -> Fr {
    let mut acc = Fr::ZERO;
    for v in values {
        acc = hash_2(acc, *v);
    }
    acc
}

/// Giống derive_challenge_index trong simulator_runner/main.rs
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
    let j_i_u64 = u64::from_le_bytes(seed_bytes.as_ref()[0..8].try_into().unwrap());
    (j_i_u64 as usize % num_chunks).saturating_add(1)
}

fn main() {
    // ── Cấu hình tí hon: 16 chunks × 4KB = 64KB, tree height 4, 3 challenges ──
    let config = EngramConfig {
        sector_size_bytes: 16 * 4096,
        chunk_size_bytes: 4096,
        tree_height: 4,
        challenges_per_epoch: 3,
        epochs_per_window: 1,
    };
    let num_chunks = config.sector_size_bytes / config.chunk_size_bytes;

    // ── Sinh raw data deterministic ──
    let path = std::env::temp_dir().join("smoke_sector.bin"); // cross-platform: /tmp trên Linux, %TEMP% trên Windows
    {
        let mut f = std::fs::File::create(&path).expect("tạo file raw data");
        let mut data = vec![0u8; config.sector_size_bytes];
        for (i, b) in data.iter_mut().enumerate() {
            *b = (i * 31 % 251) as u8;
        }
        f.write_all(&data).expect("ghi raw data");
    }

    // ── Sealing ──
    let replica_id = bytes_to_fr(b"smoke-replica-id");
    let sealer = Sealer::new(config.clone());
    let mut storage = ProverStorage::new();
    let t = Instant::now();
    let _seal_metrics = sealer.seal_sector_streaming(replica_id, &path, &mut storage);
    println!("⏱️  Sealing 64KB: {:?}", t.elapsed());
    let sealed_root = storage.merkle_tree.as_ref().expect("merkle tree").root;
    println!("🌳 sealed_root = {:?}", sealed_root);

    // ── Build 3 challenges (đúng logic simulator_runner) ──
    let epoch = 0usize;
    let sector_id = 7u64;
    let beacon = string_to_fr("smoke-beacon-000");

    let mut challenges = Vec::new();
    for c in 1..=config.challenges_per_epoch {
        let j_i = derive_challenge_index(beacon, sector_id, epoch, c, num_chunks);
        let raw_chunk = storage.get_raw_chunk(j_i).expect("raw chunk");
        let chunk_limbs = chunk_to_limbs(&raw_chunk);
        let s_prev = *storage.get_state(j_i - 1).expect("state j_i-1");
        let s_ji = *storage.get_state(j_i).expect("state j_i");
        let mp = storage
            .merkle_tree
            .as_ref()
            .unwrap()
            .generate_proof(j_i - 1);
        println!("🎯 challenge #{c}: j_i = {j_i}");
        challenges.push(EngramStepCircuit {
            epoch,
            sector_id: Fr::from(sector_id),
            sealed_root,
            beacon,
            j_i,
            s_ji_minus_1: s_prev,
            s_ji,
            replica_id,
            path_ji_siblings: mp.siblings,
            path_ji_indices: mp.path_indices,
            tree_height: config.tree_height,
            chunk_limbs,
            chunk_size_bytes: config.chunk_size_bytes,
        });
    }

    // ── Nova setup + fold + compress (HyperKZG primary, IPA secondary) ──
    let (pipeline, _setup_m) = ProvingPipeline::setup(challenges[0].clone());
    let num_steps = challenges.len();
    let (proof, z0, prove_m) = pipeline.prove_epoch(challenges);
    println!(
        "📦 Compressed proof size = {} bytes",
        prove_m.compressed_proof_size_bytes
    );

    // ── Verify ──
    let t = Instant::now();
    match proof.verify(&pipeline.vk, num_steps, &z0) {
        Ok(zn) => {
            println!("✅ VERIFY OK trong {:?}", t.elapsed());
            println!("   z_acc cuối = {:?}", zn[6]);
            println!("🎉 SMOKE TEST BN254 PASS");
        }
        Err(e) => {
            println!("❌ VERIFY FAILED: {e:?}");
            std::process::exit(1);
        }
    }
}
