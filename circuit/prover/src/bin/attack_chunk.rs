//! Kiểm chứng bản vá "chunk possession": đóng vai node GIAN LẬN.
//!
//! Phần A — mức constraint (TestConstraintSystem): honest / zeros / lật 1 byte / thiếu limb
//! Phần B — mức giao thức Nova: prove_step + RecursiveSNARK::verify trên sector đã seal thật

use core_primitives::config::EngramConfig;
use core_primitives::chunking::{bytes_to_fr, bytes_to_limbs as chunk_to_limbs, num_limbs};
use core_primitives::poseidon2::hash_2;
use core_primitives::Fr;
use ff::{Field, PrimeField};
use nova_snark::frontend::{num::AllocatedNum, test_cs::TestConstraintSystem, ConstraintSystem};
use nova_snark::nova::{PublicParams, RecursiveSNARK};
use nova_snark::traits::circuit::StepCircuit;
use nova_snark::traits::snark::RelaxedR1CSSNARKTrait;
use prover::proving::{NovaFr, SpartanPrimary, SpartanSecondary, G1, G2};
use prover::{EngramStepCircuit, ProverStorage, Sealer};
use std::io::Write;

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

fn poseidon2_hash_4(a: Fr, b: Fr, c: Fr, d: Fr) -> Fr {
    hash_2(hash_2(a, b), hash_2(c, d))
}

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

fn nova(f: Fr) -> NovaFr {
    NovaFr::from_repr(f.to_repr().into()).unwrap_or(NovaFr::ZERO)
}

// ───────────────────────── PHẦN A: mức constraint ─────────────────────────

/// Dựng circuit hợp lệ hoàn toàn (tự tính sealed_root khớp), rồi cho phép
/// thay chunk_limbs bằng witness gian lận.
fn build_test_circuit(chunk: &[u8], limbs_override: Option<Vec<Fr>>) -> (EngramStepCircuit, Fr, Fr) {
    let beacon = string_to_fr("attack_beacon");
    let sector_id = 1000u64;
    let epoch = 0usize;
    let num_chunks = 262144usize;
    let j_i = derive_challenge_index(beacon, sector_id, epoch, 1, num_chunks);

    // d_ji LUÔN là digest của chunk THẬT (node gian lận vẫn giữ 32 byte này)
    let d_ji = bytes_to_fr(chunk);
    let chunk_limbs = limbs_override.unwrap_or_else(|| chunk_to_limbs(chunk));

    let s_ji_minus_1 = Fr::ZERO;
    let replica_id = Fr::ZERO;
    let r_ji = poseidon2_hash_4(d_ji, s_ji_minus_1, Fr::from(j_i as u64), replica_id);
    let s_ji = hash_2(s_ji_minus_1, r_ji);

    let j_i_minus_1 = j_i.saturating_sub(1);
    let path_ji_indices: Vec<bool> = (0..18).map(|b| (j_i_minus_1 >> b) & 1 == 1).collect();
    let path_ji_siblings = vec![Fr::ZERO; 18];
    let mut cur = hash_2(r_ji, s_ji);
    for bit in 0..18 {
        cur = if (j_i_minus_1 >> bit) & 1 == 1 {
            hash_2(Fr::ZERO, cur)
        } else {
            hash_2(cur, Fr::ZERO)
        };
    }
    let sealed_root = cur;

    (
        EngramStepCircuit {
            epoch,
            sector_id: Fr::from(sector_id),
            sealed_root,
            beacon,
            j_i,
            s_ji_minus_1,
            s_ji,
            replica_id,
            path_ji_siblings,
            path_ji_indices,
            tree_height: 18,
            chunk_limbs,
            chunk_size_bytes: 4096,
        },
        sealed_root,
        beacon,
    )
}

fn run_cs_case(label: &str, chunk: &[u8], limbs_override: Option<Vec<Fr>>) {
    let (circuit, sealed_root, beacon) = build_test_circuit(chunk, limbs_override);
    let n_limbs = circuit.chunk_limbs.len();
    let mut cs = TestConstraintSystem::<NovaFr>::new();
    let z: Vec<AllocatedNum<NovaFr>> = vec![
        (NovaFr::ZERO, "z0"),
        (NovaFr::ZERO, "z1"),
        (nova(circuit.sector_id), "z2"),
        (nova(sealed_root), "z3"),
        (nova(beacon), "z4"),
        (NovaFr::ZERO, "z5"),
        (NovaFr::ZERO, "z6"),
    ]
    .into_iter()
    .map(|(v, n)| AllocatedNum::alloc(cs.namespace(|| n), || Ok(v)).unwrap())
    .collect();

    match circuit.synthesize(&mut cs, &z) {
        Err(e) => println!(
            "  {:<38} limbs={:>3}  → LÁ CHẮN 1: circuit từ chối dựng witness\n      → {}",
            label, n_limbs, e
        ),
        Ok(_) => {
            let sat = cs.is_satisfied();
            println!(
                "  {:<38} limbs={:>3}  constraints={:>6}  satisfied={}",
                label,
                n_limbs,
                cs.num_constraints(),
                if sat { "✅ TRUE" } else { "❌ FALSE" }
            );
            if !sat {
                println!("      → LÁ CHẮN 2, constraint fail: {:?}", cs.which_is_unsatisfied());
            }
        }
    }
}

// ───────────────────────── PHẦN B: mức giao thức Nova ─────────────────────────

fn part_b() {
    let config = EngramConfig {
        sector_size_bytes: 16 * 4096,
        chunk_size_bytes: 4096,
        tree_height: 4,
        challenges_per_epoch: 1,
        epochs_per_window: 1,
    };
    let num_chunks = config.sector_size_bytes / config.chunk_size_bytes;

    let path = std::env::temp_dir().join("attack_sector.bin"); // cross-platform: /tmp trên Linux, %TEMP% trên Windows
    let mut data = vec![0u8; config.sector_size_bytes];
    for (i, b) in data.iter_mut().enumerate() {
        *b = (i * 31 % 251) as u8;
    }
    std::fs::File::create(&path).unwrap().write_all(&data).unwrap();

    let replica_id = bytes_to_fr(b"attack-replica");
    let sealer = Sealer::new(config.clone());
    let mut storage = ProverStorage::new();
    sealer.seal_sector_streaming(replica_id, &path, &mut storage);
    let sealed_root = storage.merkle_tree.as_ref().unwrap().root;

    let epoch = 0usize;
    let sector_id = 7u64;
    let beacon = string_to_fr("attack-beacon-b");
    let j_i = derive_challenge_index(beacon, sector_id, epoch, 1, num_chunks);
    let raw = storage.get_raw_chunk(j_i).unwrap();
    let mp = storage.merkle_tree.as_ref().unwrap().generate_proof(j_i - 1);

    let mk = |limbs: Vec<Fr>| EngramStepCircuit {
        epoch,
        sector_id: Fr::from(sector_id),
        sealed_root,
        beacon,
        j_i,
        s_ji_minus_1: *storage.get_state(j_i - 1).unwrap(),
        s_ji: *storage.get_state(j_i).unwrap(),
        replica_id,
        path_ji_siblings: mp.siblings.clone(),
        path_ji_indices: mp.path_indices.clone(),
        tree_height: config.tree_height,
        chunk_limbs: limbs,
        chunk_size_bytes: config.chunk_size_bytes,
    };

    let honest = mk(chunk_to_limbs(&raw));
    println!("  Đang setup PublicParams (shape lấy từ circuit HỢP LỆ 133 limbs)...");
    let pp = PublicParams::<G1, G2, EngramStepCircuit>::setup(
        &honest,
        &*SpartanPrimary::ck_floor(),
        &*SpartanSecondary::ck_floor(),
    )
    .unwrap();
    println!(
        "  → shape primary: {} constraints, {} vars",
        pp.num_constraints().0,
        pp.num_variables().0
    );

    let z0 = vec![
        NovaFr::from(epoch as u64),
        NovaFr::ZERO,
        nova(Fr::from(sector_id)),
        nova(sealed_root),
        nova(beacon),
        nova(replica_id),
        nova(replica_id),
    ];

    let try_case = |label: &str, c: EngramStepCircuit| {
        let mut rs = match RecursiveSNARK::new(&pp, &c, &z0) {
            Ok(r) => r,
            Err(e) => {
                println!("  {:<34} → RecursiveSNARK::new Err: {:?}", label, e);
                return;
            }
        };
        match rs.prove_step(&pp, &c) {
            Ok(()) => match rs.verify(&pp, 1, &z0) {
                Ok(_) => println!("  {:<34} → prove OK, verify ✅ PASS", label),
                Err(e) => println!(
                    "  {:<34} → prove OK nhưng verify ❌ REJECT: {}",
                    label,
                    format!("{:?}", e).chars().take(60).collect::<String>()
                ),
            },
            Err(e) => println!(
                "  {:<34} → prove_step ❌ Err: {}",
                label,
                format!("{:?}", e).chars().take(60).collect::<String>()
            ),
        }
    };

    try_case("Node TRUNG THỰC (limbs thật)", honest);
    try_case(
        "Node GIAN LẬN (chỉ giữ d_ji, zeros)",
        mk(vec![Fr::ZERO; num_limbs(4096)]),
    );
    let mut corrupted = raw.clone();
    corrupted[0] ^= 0x01;
    try_case("Node LÀM HỎNG data (lật 1 bit)", mk(chunk_to_limbs(&corrupted)));
    let mut short = chunk_to_limbs(&raw);
    short.truncate(132);
    try_case("Node GỬI THIẾU limb (132/133)", mk(short));
}

fn main() {
    let chunk: Vec<u8> = (0..4096).map(|i| (i * 31 % 251) as u8).collect();

    println!("\n═══ PHẦN A — mức constraint (TestConstraintSystem) ═══");
    run_cs_case("Node TRUNG THỰC", &chunk, None);
    run_cs_case(
        "Node GIAN LẬN: chỉ giữ d_ji → limbs = 0",
        &chunk,
        Some(vec![Fr::ZERO; num_limbs(4096)]),
    );
    let mut corrupted = chunk.clone();
    corrupted[2000] ^= 0x01;
    run_cs_case(
        "Node LÀM HỎNG data: lật 1 bit ở giữa",
        &chunk,
        Some(chunk_to_limbs(&corrupted)),
    );
    let mut short = chunk_to_limbs(&chunk);
    short.truncate(132);
    run_cs_case("Node GỬI THIẾU limb (132/133)", &chunk, Some(short));
    let mut extra = chunk_to_limbs(&chunk);
    extra.push(Fr::ZERO);
    run_cs_case("Node GỬI THỪA limb (134/133)", &chunk, Some(extra));

    println!("\n═══ PHẦN B — mức giao thức Nova (sector seal thật) ═══");
    part_b();
    println!();
}
