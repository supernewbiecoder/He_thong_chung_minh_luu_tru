//! PV-STUB HOST — sinh MỘT Groth16 proof THẬT cho guest tối giản.
//!
//!   --execute            đếm cycle của stub (rẻ, để chứng minh nó thật sự nhỏ)
//!   --prove              sinh Groth16 (cần circuit artifact gnark trong ~/.sp1)
//!   --out <dir>          nơi lưu proof.bin / public_values.bin / vkey.txt
//!   --json <file>        append một dòng JSONL
//!
//! GIÁ TRỊ MẶC ĐỊNH của các root trùng khớp hằng số trong
//! `experiments/l4_evm/bench_evm.py`, để `bench_real_verifier.py` deploy
//! EngramAttestation với đúng `storageVkDigest` và truyền đúng
//! `blobstreamDataRoot` / `blobstreamResultsDataRoot` mà không cần sửa gì.
//!
//! ⚠ `--submitter` PHẢI là địa chỉ sẽ gửi transaction trên Anvil, nếu không
//! contract revert `SubmitterMismatch`. Mặc định là account #0 của Anvil.

use clap::Parser;
use sp1_sdk::blocking::{ProveRequest, Prover, ProverClient};
use sp1_sdk::{include_elf, HashableKey, ProvingKey, SP1Stdin};
use sp1_shared::PublicValues;
use std::path::PathBuf;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tiny_keccak::{Hasher, Keccak};

pub const GUEST_ELF: sp1_sdk::Elf = include_elf!("engram-pvstub-guest");

#[derive(Parser)]
struct Args {
    #[clap(long)]
    execute: bool,
    #[clap(long)]
    prove: bool,

    #[clap(long, default_value = "1")]
    epoch: u64,
    /// Chỉ là một trường uint32 trong PV — không đổi chi phí gì. Phải > 0.
    #[clap(long, default_value = "1")]
    num_verified: u32,

    /// Account gửi tx trên Anvil (account #0 mặc định của Anvil).
    #[clap(long, default_value = "f39fd6e51aad88f6f4ce6ab8827279cfffb92266")]
    submitter: String,

    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000002222")]
    batch_root: String,
    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000001111")]
    data_root: String,
    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000003333")]
    results_root: String,
    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000004444")]
    results_data_root: String,
    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000005151")]
    storage_vk_digest: String,
    /// ★ snapshot_id — hợp đồng từ chối giá trị 0.
    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000009901")]
    snapshot_id: String,
    /// currentStateRoot của contract trước khi commit. Contract mới deploy = 0.
    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000000000")]
    prev_state_root: String,

    #[clap(long, default_value = "/results/pvstub")]
    out: String,
    #[clap(long)]
    json: Option<String>,
    #[clap(long, default_value = "pvstub")]
    run_id: String,
}

fn parse_fixed_hex<const N: usize>(name: &str, value: &str) -> [u8; N] {
    let trimmed = value.strip_prefix("0x").unwrap_or(value);
    let bytes = hex::decode(trimmed).unwrap_or_else(|_| {
        eprintln!("--{name} phải là chuỗi hex hợp lệ");
        std::process::exit(2);
    });
    if bytes.len() != N {
        eprintln!("--{name} phải đúng {N} byte, nhận {}", bytes.len());
        std::process::exit(2);
    }
    let mut out = [0u8; N];
    out.copy_from_slice(&bytes);
    out
}

fn keccak256(data: &[u8]) -> [u8; 32] {
    let mut h = Keccak::v256();
    h.update(data);
    let mut out = [0u8; 32];
    h.finalize(&mut out);
    out
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn peak_rss_kib() -> u64 {
    std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|s| {
            s.lines()
                .find(|l| l.starts_with("VmHWM:"))
                .and_then(|l| l.split_whitespace().nth(1).and_then(|v| v.parse().ok()))
        })
        .unwrap_or(0)
}

fn cgroup_peak_bytes() -> u64 {
    for p in [
        "/sys/fs/cgroup/memory.peak",
        "/sys/fs/cgroup/memory/memory.max_usage_in_bytes",
    ] {
        if let Ok(raw) = std::fs::read_to_string(p) {
            if let Ok(v) = raw.trim().parse::<u64>() {
                return v;
            }
        }
    }
    0
}

fn append_json(path: &str, line: &str) {
    use std::io::Write;
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .expect("không mở được file json");
    writeln!(f, "{}", line).expect("ghi json lỗi");
    f.flush().ok();
    f.sync_all().ok();
    println!("📝 Đã ghi kết quả vào {}", path);
}

fn main() {
    sp1_sdk::utils::setup_logger();
    let args = Args::parse();

    if std::env::var("SP1_PROVER")
        .map(|v| v.eq_ignore_ascii_case("network"))
        .unwrap_or(false)
    {
        eprintln!("SP1_PROVER=network bị khóa trong build này. Chỉ local execute/prove.");
        std::process::exit(2);
    }
    if args.execute == args.prove {
        eprintln!("Chọn ĐÚNG MỘT: --execute hoặc --prove");
        std::process::exit(1);
    }
    if args.num_verified == 0 {
        eprintln!("--num-verified phải > 0 (contract revert EmptyBatchNotAllowed)");
        std::process::exit(2);
    }

    let batch_root: [u8; 32] = parse_fixed_hex("batch-root", &args.batch_root);
    let data_root: [u8; 32] = parse_fixed_hex("data-root", &args.data_root);
    let results_root: [u8; 32] = parse_fixed_hex("results-root", &args.results_root);
    let results_data_root: [u8; 32] =
        parse_fixed_hex("results-data-root", &args.results_data_root);
    let storage_vk_digest: [u8; 32] =
        parse_fixed_hex("storage-vk-digest", &args.storage_vk_digest);
    let snapshot_id: [u8; 32] = parse_fixed_hex("snapshot-id", &args.snapshot_id);
    let prev_state_root: [u8; 32] = parse_fixed_hex("prev-state-root", &args.prev_state_root);
    let submitter: [u8; 20] = parse_fixed_hex("submitter", &args.submitter);

    if results_root == [0u8; 32] {
        eprintln!("--results-root phải khác 0 (contract revert ResultsRootMissing)");
        std::process::exit(2);
    }

    // Cùng công thức với guest thật và với contract.
    let new_state_root = {
        let mut buf = Vec::with_capacity(32 + 32 + 32 + 8);
        buf.extend_from_slice(&prev_state_root);
        buf.extend_from_slice(&batch_root);
        buf.extend_from_slice(&results_root);
        buf.extend_from_slice(&snapshot_id);
        buf.extend_from_slice(&storage_vk_digest);
        buf.extend_from_slice(&args.epoch.to_be_bytes());
        keccak256(&buf)
    };

    let pv = PublicValues {
        epoch: args.epoch,
        batch_root,
        data_root,
        results_root,
        results_data_root,
        storage_vk_digest,
        snapshot_id,
        submitter,
        prev_state_root,
        new_state_root,
        num_verified: args.num_verified,
    };
    let pv_packed = pv.to_packed();
    println!("📦 PV dựng sẵn: {} byte", pv_packed.len());
    println!("   epoch={} num_verified={}", pv.epoch, pv.num_verified);
    println!("   new_state_root = 0x{}", hex::encode(pv.new_state_root));

    let dir = PathBuf::from(&args.out);
    std::fs::create_dir_all(&dir).expect("không tạo được thư mục out");
    std::fs::write(dir.join("pv_expected.bin"), pv_packed)
        .expect("không ghi được pv_expected.bin");

    let mut stdin = SP1Stdin::new();
    stdin.write(&pv_packed.to_vec());

    let client = ProverClient::from_env();

    if args.execute {
        println!("\n🔍 EXECUTE — đếm cycle của pv-stub guest...");
        let t0 = Instant::now();
        let (public_values, report) = client
            .execute(GUEST_ELF.clone(), stdin)
            .run()
            .expect("execute thất bại");
        let elapsed = t0.elapsed().as_secs_f64();
        let cycles = report.total_instruction_count();
        let prover_gas = report.gas().unwrap_or(0);
        let out_pv = public_values.as_slice().to_vec();
        let ok = out_pv.len() == sp1_shared::PV_PACKED_LEN && out_pv == pv_packed.to_vec();

        println!("📊 TỔNG CYCLES:      {}", cycles);
        println!("⛽ PROVER GAS:       {}", prover_gas);
        println!("⏱️  Execute time:     {:.2}s", elapsed);
        println!("✅ PV commit ra:     {} byte (khớp input: {})", out_pv.len(), ok);

        let rec = format!(
            r#"{{"mode":"pvstub_execute","ok":{},"run_id":"{}","ts":{},"cycles":{},"prover_gas":{},"execute_s":{:.2},"pv_bytes":{},"peak_rss_kib":{},"cgroup_memory_peak_bytes":{}}}"#,
            ok, args.run_id, now_secs(), cycles, prover_gas, elapsed,
            out_pv.len(), peak_rss_kib(), cgroup_peak_bytes()
        );
        if let Some(p) = &args.json {
            append_json(p, &rec);
        }
        if !ok {
            eprintln!("\n❌ PV commit ra không khớp PV đưa vào — không dùng làm số đo.");
            std::process::exit(4);
        }
        return;
    }

    // ── PROVE ──
    println!("\n🔐 LOCAL GROTH16 (pv-stub) — không dùng prover network...");
    println!("⚠ Cần circuit artifact gnark trong ~/.sp1 (~30 GB). Không có mạng và");
    println!("  không có cache thì bước này sẽ FAIL vì không tải được, KHÔNG phải OOM.");

    let pk = client.setup(GUEST_ELF.clone()).expect("setup thất bại");
    let vkey_bytes32 = pk.verifying_key().bytes32();
    println!("🔑 programVKey = {}", vkey_bytes32);
    std::fs::write(dir.join("vkey.txt"), vkey_bytes32.as_bytes())
        .expect("không ghi được vkey.txt");

    let t = Instant::now();
    let proof = client
        .prove(&pk, stdin)
        .groth16()
        .run()
        .expect("prove thất bại");
    let prove_s = t.elapsed().as_secs_f64();

    let proof_bytes = proof.bytes();
    let out_pv = proof.public_values.as_slice().to_vec();
    let vk = pk.verifying_key();
    client.verify(&proof, vk, None).expect("Groth16 verify FAIL");

    // Lưu artifact TRƯỚC khi kiểm — proof này tốn giờ, không được để mất.
    std::fs::write(dir.join("proof.bin"), &proof_bytes).expect("không ghi được proof.bin");
    std::fs::write(dir.join("public_values.bin"), &out_pv)
        .expect("không ghi được public_values.bin");

    let selector = if proof_bytes.len() >= 4 {
        hex::encode(&proof_bytes[..4])
    } else {
        String::new()
    };
    let ok = out_pv.len() == sp1_shared::PV_PACKED_LEN && out_pv == pv_packed.to_vec();

    println!("✅ Groth16 proof:    {} byte", proof_bytes.len());
    println!("✅ Public values:    {} byte", out_pv.len());
    println!(
        "✅ EVM calldata thô: {} byte (proof + public values, chưa gồm ABI head)",
        proof_bytes.len() + out_pv.len()
    );
    println!("🔎 4-byte selector:  0x{}  ← dùng để tìm đúng SP1Verifier version", selector);
    println!("⏱️  Prove time:       {:.1}s", prove_s);
    println!("🧠 Peak RSS:         {:.2} GiB", peak_rss_kib() as f64 / 1048576.0);
    println!("🧠 Cgroup peak:      {:.2} GiB", cgroup_peak_bytes() as f64 / 1073741824.0);
    println!("💾 Artifact:         {}", dir.display());

    let rec = format!(
        r#"{{"mode":"pvstub_prove","ok":{},"run_id":"{}","ts":{},"prove_s":{:.1},"groth16_bytes":{},"public_values_bytes":{},"evm_calldata_bytes":{},"selector":"0x{}","vkey":"{}","peak_rss_kib":{},"cgroup_memory_peak_bytes":{}}}"#,
        ok, args.run_id, now_secs(), prove_s, proof_bytes.len(), out_pv.len(),
        proof_bytes.len() + out_pv.len(), selector, vkey_bytes32,
        peak_rss_kib(), cgroup_peak_bytes()
    );
    std::fs::write(dir.join("result.json"), format!("{}\n", rec))
        .expect("không ghi được result.json");
    if let Some(p) = &args.json {
        append_json(p, &rec);
    }

    if !ok {
        eprintln!(
            "\n❌ PV commit ra ({} byte) không khớp PV đưa vào ({} byte). Artifact vẫn đã lưu để chẩn đoán.",
            out_pv.len(),
            pv_packed.len()
        );
        std::process::exit(5);
    }
    println!("\n✅ HỢP LỆ. Bước tiếp: experiments/l4_evm/bench_real_verifier.py");
}
