//! HOST DRIVER — Điều phối SP1 (API 6.3.1 blocking). KHÔNG kéo theo nova/prover.
//!
//!   --execute --batch N : Chạy guest, ĐẾM SỐ CHU KỲ (CYCLES) cho batch N bundle. RẺ, không sinh proof.
//!   --prove   --batch N : Sinh Groth16 proof cho batch N bundle. ĐẮT (Yêu cầu RAM lớn + Docker).
//!   --json <file>       : Ghi thêm 1 dòng kết quả dạng JSONL để script tổng hợp quét.
//!
//! GHI CHÚ ĐO ĐẠC (cần nêu trong báo cáo): Với --batch N > 1, theo mặc định, host sẽ nhân bản CÙNG
//! một ProofBundle N lần. Chi phí xác minh của CompressedSNARK KHÔNG phụ thuộc vào giá trị của dữ
//! liệu (do cùng số phép pairing/MSM/sumcheck), vì vậy số chu kỳ đo được TƯƠNG ĐƯƠNG với N proof
//! phân biệt — nhưng giúp tiết kiệm hàng giờ để sinh proof Nova.
//!
//! ── ĐIỂM ĐỐI CHỨNG ──
//! `--distinct-dir <dir>` nạp các bundle PHÂN BIỆT có thật thay vì nhân bản. Chạy cả hai
//! với cùng giá trị N rồi so sánh số chu kỳ là bằng chứng cho ghi chú đo đạc ở trên.
//!
//! ⚠ Các bundle này PHẢI được sinh bằng lệnh `bundle_gen --num-bundles N` trong CÙNG MỘT tiến trình.
//! Chạy `bundle_gen` N lần riêng lẻ vào cùng một thư mục là SAI: `PublicParams::setup` của
//! nova (tính năng `test-utils`) không có tính tất định, mỗi lần chạy sẽ ghi đè `vk.bin` bằng một vk khác,
//! dẫn đến việc N-1 bundle mất vk của chúng và việc xác minh thất bại bên trong guest.
//!
//! ═══════════════════════════════════════════════════════════════════════════
//! ⚠ THAY ĐỔI: GHI DỮ LIỆU JSONL TRƯỚC KHI DIỄN GIẢI PUBLIC VALUES
//! ═══════════════════════════════════════════════════════════════════════════
//! Phiên bản trước đây gọi `public_values.read()` NGAY sau khi thực thi, rồi mới ghi JSONL. Khi guest
//! không commit gì cả (việc xác minh thất bại trong zkVM), `read()` sẽ panic với lỗi `UnexpectedEof` và toàn
//! bộ kết quả đếm chu kỳ — vốn tốn hàng chục phút tính toán — sẽ bị mất trắng mà không có dòng nào được
//! ghi ra đĩa.
//!
//! Nguyên tắc: **Số chu kỳ (cycles) là KẾT QUẢ ĐO ĐẠC, public values chỉ là phần DIỄN GIẢI.** Kết quả đo phải
//! được lưu trước tiên và không bao giờ được phép mất đi chỉ vì khâu diễn giải gặp lỗi.

use clap::Parser;
use sp1_sdk::blocking::{ProveRequest, Prover, ProverClient};
use sp1_sdk::{include_elf, HashableKey, ProvingKey, SP1Stdin};
use sp1_shared::{GuestInput, ProofBundle, PublicValues};
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

pub const GUEST_ELF: sp1_sdk::Elf = include_elf!("engram-guest");
const MAX_BATCH: usize = 4_096;
const MAX_BUNDLE_FILE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_VK_FILE_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Parser)]
struct Args {
    #[clap(long)]
    execute: bool,
    #[clap(long)]
    prove: bool,
    /// Số lượng bundle trong batch (nhân bản bundle.bin). Đây là trục chính của RQ2.
    #[clap(long, default_value = "1")]
    batch: usize,
    #[clap(long, default_value = "../artifacts")]
    artifacts: String,
    /// Ghi kết quả JSON vào tệp (thêm 1 dòng mỗi lần chạy) để script có thể quét và tổng hợp.
    #[clap(long)]
    json: Option<String>,

    /// Nạp các bundle PHÂN BIỆT từ thư mục này (tất cả các tệp `bundle*.bin`, sắp xếp theo tên)
    /// thay vì nhân bản một bundle duy nhất. Tùy chọn --batch bị BỎ QUA; batch = số lượng tệp tìm được.
    #[clap(long)]
    distinct_dir: Option<String>,

    /// Định danh của lượt chạy (do sweep.sh sinh ra) — dùng để phân biệt các lần đo đạc trong JSONL.
    #[clap(long, default_value = "na")]
    run_id: String,

    /// Nhãn giai đoạn (phase) ("smoke" | "1a" | "1b" | "2" | "3" | "distinct") — được ghi vào JSONL.
    #[clap(long, default_value = "na")]
    phase: String,

    /// ★ ĐÃ BỎ `--results-root`: Guest giờ đây tự tính toán gốc quyết toán (settlement root) 
    /// từ kết quả xác minh của từng bundle. Việc truyền vào từ bên ngoài không còn ý nghĩa, 
    /// và bỏ đối số này là cách chặn từ tầng giao diện chứ không chỉ ở tầng tài liệu.
    ///
    /// Celestia data root chứa settlement manifest (hex bytes32).
    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000000000")]
    results_data_root: String,
    /// Địa chỉ EVM (EVM address) được bind vào final proof nhằm chống việc copy/front-run.
    #[clap(long, default_value = "0000000000000000000000000000000000000000")]
    submitter: String,
    /// ★ Định danh ảnh chụp của epoch (hex bytes32). Hợp đồng từ chối giá trị 0,
    /// do đó mặc định là một hằng số khác 0 để benchmark có thể chạy được.
    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000009901")]
    snapshot_id: String,

    /// ★ Gốc dữ liệu DA (DA data root) của epoch (hex bytes32).
    ///
    /// Trước đây trường này bị gán cứng bằng 0 vì lớp DA chưa được kết nối. Hiện nay
    /// script điều phối E2E lấy giá trị THỰC TẾ từ node Celestia rồi truyền vào
    /// đây; hợp đồng sẽ đối chiếu với oracle độc lập được nạp cùng giá trị đó.
    ///
    /// Lưu ý: Việc thêm đối số này KHÔNG làm thay đổi tệp ELF của guest, nên khóa chương
    /// trình (program key) và số chu kỳ đã đo vẫn được giữ nguyên. Guest chỉ chép giá trị ra
    /// public values — kích thước bincode của [u8; 32] không phụ thuộc vào nội dung.
    ///
    /// Điều này vẫn CHƯA chứng minh các bundle nằm TRONG gốc đó; việc này yêu cầu
    /// guest xác minh bằng chứng tồn tại trên cây theo namespace (trường `da`).
    #[clap(long, default_value = "0000000000000000000000000000000000000000000000000000000000000000")]
    data_root: String,
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

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Đỉnh RSS (KiB) lấy từ /proc/self/status VmHWM.
///
/// ⚠ VmHWM KHÔNG tính bộ nhớ tmpfs (/dev/shm), trong khi SP1 executor lại sử dụng shm khá nhiều (có thể thấy
/// ở cột `shared` của lệnh `free -h`). Cgroup thì CÓ tính phần này vào `--memory`. Do đó, đừng ngoại suy mức trần
/// N từ trường này — hãy dùng `docker stats` để lấy số đỉnh thực tế.
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

/// Đọc một bộ đếm (counter) bộ nhớ cgroup v2/v1. Khác với VmHWM chỉ tính riêng cho tiến trình
/// host, bộ đếm này tính cả các executor con và tmpfs (/dev/shm). Trong một
/// container chỉ chạy đúng một điểm benchmark, `memory.peak` là đỉnh RAM gần
/// đúng nhất với lượng RAM mà Docker thực sự phải cấp phát cho điểm đó.
fn cgroup_counter(paths: &[&str]) -> u64 {
    paths
        .iter()
        .find_map(|path| {
            std::fs::read_to_string(path).ok().and_then(|raw| {
                let value = raw.trim();
                if value == "max" {
                    None
                } else {
                    value.parse::<u64>().ok()
                }
            })
        })
        .unwrap_or(0)
}

fn cgroup_memory_current_bytes() -> u64 {
    cgroup_counter(&[
        "/sys/fs/cgroup/memory.current",
        "/sys/fs/cgroup/memory/memory.usage_in_bytes",
    ])
}

fn cgroup_memory_peak_bytes() -> u64 {
    cgroup_counter(&[
        "/sys/fs/cgroup/memory.peak",
        "/sys/fs/cgroup/memory/memory.max_usage_in_bytes",
    ])
}

/// Đọc tệp meta.json do `bundle_gen` ghi ra và nhúng NGUYÊN VĂN vào dòng JSONL dưới khóa "cfg".
/// Nhờ vậy, mỗi dòng kết quả sẽ tự mang theo thông tin về `tree_height` và `sector_size` đã tạo ra nó.
fn read_cfg(dir: &Path) -> String {
    match std::fs::read_to_string(dir.join("meta.json")) {
        Ok(s) => {
            let t = s.trim().to_string();
            if t.starts_with('{') && t.ends_with('}') {
                t
            } else {
                "{}".to_string()
            }
        }
        Err(_) => "{}".to_string(),
    }
}

fn load_bundle(path: &Path) -> ProofBundle {
    let size = std::fs::metadata(path)
        .map(|meta| meta.len())
        .unwrap_or_else(|e| {
            eprintln!("Không stat được {}: {}", path.display(), e);
            std::process::exit(1);
        });
    if size > MAX_BUNDLE_FILE_BYTES {
        eprintln!(
            "Từ chối bundle {}: {} byte vượt cap {} byte (pre-deserialize DoS guard)",
            path.display(),
            size,
            MAX_BUNDLE_FILE_BYTES
        );
        std::process::exit(2);
    }
    let bytes = std::fs::read(path).unwrap_or_else(|e| {
        eprintln!("Không đọc được {}: {}", path.display(), e);
        std::process::exit(1);
    });
    bincode::deserialize(&bytes).unwrap_or_else(|e| {
        eprintln!(
            "{} hỏng hoặc lệch version nova: {}\n\
             (bundle_gen và guest phải dùng CÙNG nova-snark — commit Cargo.lock!)",
            path.display(),
            e
        );
        std::process::exit(1);
    })
}

fn main() {
    sp1_sdk::utils::setup_logger();
    let args = Args::parse();
    if std::env::var("SP1_PROVER")
        .map(|value| value.eq_ignore_ascii_case("network"))
        .unwrap_or(false)
    {
        eprintln!(
            "SP1_PROVER=network is disabled in this simulation build. Use local execute/prove only."
        );
        std::process::exit(2);
    }
    if args.execute == args.prove {
        eprintln!("Chọn ĐÚNG MỘT: --execute hoặc --prove");
        std::process::exit(1);
    }
    if args.batch == 0 || args.batch > MAX_BATCH {
        eprintln!("--batch phải trong 1..={MAX_BATCH}, nhận {}", args.batch);
        std::process::exit(2);
    }

    let dir = PathBuf::from(&args.artifacts);
    let vk_path = dir.join("vk.bin");
    let vk_size = std::fs::metadata(&vk_path).map(|meta| meta.len()).unwrap_or(0);
    if vk_size == 0 || vk_size > MAX_VK_FILE_BYTES {
        eprintln!("vk.bin rỗng hoặc vượt cap {} byte", MAX_VK_FILE_BYTES);
        std::process::exit(2);
    }
    let vk_bytes = std::fs::read(&vk_path).unwrap_or_else(|_| {
        eprintln!("Thiếu {}/vk.bin — chạy bundle-gen trước.", args.artifacts);
        std::process::exit(1);
    });
    let cfg = read_cfg(&dir);

    // ── Nạp bundle: phân biệt (để đối chứng) hoặc nhân bản (mặc định) ──
    let (bundles, distinct) = match &args.distinct_dir {
        Some(d) => {
            let ddir = PathBuf::from(d);
            let mut paths: Vec<PathBuf> = std::fs::read_dir(&ddir)
                .unwrap_or_else(|e| {
                    eprintln!("Không đọc được thư mục {}: {}", ddir.display(), e);
                    std::process::exit(1);
                })
                .filter_map(|e| e.ok().map(|e| e.path()))
                .filter(|p| {
                    p.file_name()
                        .and_then(|n| n.to_str())
                        .map(|n| n.starts_with("bundle") && n.ends_with(".bin"))
                        .unwrap_or(false)
                })
                .collect();
            paths.sort();
            if paths.is_empty() {
                eprintln!("Không thấy bundle*.bin nào trong {}", ddir.display());
                std::process::exit(1);
            }
            if paths.len() > MAX_BATCH {
                eprintln!("Có {} bundle, vượt MAX_BATCH={MAX_BATCH}", paths.len());
                std::process::exit(2);
            }
            println!("🔀 Chế độ ĐỐI CHỨNG: {} bundle phân biệt", paths.len());

            // ⚠ NGĂN CHẶN SỚM lỗi làm lãng phí hàng chục phút: nếu các bundle không được sinh bằng cờ
            // `--num-bundles`, mỗi bundle sẽ có khóa xác minh (vk) riêng và chỉ có vk của bundle cuối cùng
            // được giữ lại trong thư mục. Điều này sẽ khiến guest xác minh thất bại. Phát hiện sớm lúc này sẽ tiết kiệm chi phí hơn rất nhiều.
            // ④ Kiểm tra SỐ LƯỢNG thay vì chỉ kiểm tra cờ. Trước đây, mã nguồn chỉ so sánh
            // `"shared_vk":true`, nhưng `bundle_gen` luôn ghi giá trị `true` bất kể
            // `--num-bundles` là bao nhiêu → cơ chế bảo vệ bị vô hiệu hóa (no-op) trong chính tình huống
            // lỗi mà nó được thiết kế để ngăn chặn. Giờ đây, `bundle_gen` ghi lại số lượng thực tế,
            // và host sẽ đối chiếu thêm trường `num_bundles` với số lượng tệp đếm được.
            let claims_count = format!("\"num_bundles\":{}", paths.len());
            if paths.len() > 1
                && (!cfg.contains("\"shared_vk\":true")
                    || !cfg.contains(&claims_count))
            {
                eprintln!(
                    "\n❌ {} bundle nhưng meta.json KHÔNG có \"shared_vk\":true.\n\
                     Nhiều khả năng chúng được sinh ra bằng nhiều lần chạy bundle_gen riêng lẻ,\n\
                     mỗi lần sử dụng một PublicParams khác nhau → vk.bin bị ghi đè, các bundle còn lại\n\
                     bị mất vk tương ứng của chúng và sẽ xác minh THẤT BẠI bên trong guest.\n\n\
                     Vui lòng sinh lại bằng MỘT lệnh duy nhất:\n\
                     \x20 bundle-gen --num-bundles {} --challenges <C> --tree-height <H> \\\n\
                     \x20             --out {} --scratch <scratch>\n",
                    paths.len(),
                    paths.len(),
                    ddir.display()
                );
                std::process::exit(3);
            }

            let bs: Vec<ProofBundle> = paths.iter().map(|p| load_bundle(p)).collect();
            (bs, true)
        }
        None => {
            let b = load_bundle(&dir.join("bundle.bin"));
            let bs: Vec<ProofBundle> = (0..args.batch).map(|_| b.clone()).collect();
            (bs, false)
        }
    };

    let batch = bundles.len();
    let num_steps = bundles[0].num_steps;
    let one_bundle_bytes = bundles[0].proof_bytes.len();
    // Đối với các bundle phân biệt, chúng ta thực hiện phép cộng thực tế thay vì phép nhân — kích thước có thể chênh lệch nhẹ.
    let da_payload_bytes: usize = bundles.iter().map(|b| b.proof_bytes.len()).sum();

    println!(
        "📦 Batch: {} bundle × {} challenges/proof | payload DA = {} bytes ({:.1} KB) | distinct={}",
        batch,
        num_steps,
        da_payload_bytes,
        da_payload_bytes as f64 / 1024.0,
        distinct
    );

    // ⚠ prev_state_root hiện tại vẫn là hằng số 0 (chuỗi trạng thái khởi đầu từ 0).
    //   Trường data_root nay đã được nhận từ đối số --data-root; xem thêm phần chú thích ở khai báo đối số.
    // Việc đo đạc số chu kỳ (cycles) hay phí gas vẫn hoàn toàn hợp lệ (do chúng không phụ
    // thuộc vào giá trị của hai trường này). Tuy nhiên, chuỗi trạng thái đa epoch (multi-epoch state) và các ràng buộc DA
    // CHƯA được thực thi. Đây thuộc về phạm vi của Giai đoạn 3 và cần được nêu rõ ở phần Hạn chế (Limitations).
    let input = GuestInput {
        epoch: bundles[0].epoch,
        data_root: parse_fixed_hex("data-root", &args.data_root),
        results_data_root: parse_fixed_hex(
            "results-data-root",
            &args.results_data_root,
        ),
        snapshot_id: parse_fixed_hex("snapshot-id", &args.snapshot_id),
        submitter: parse_fixed_hex("submitter", &args.submitter),
        prev_state_root: [0u8; 32],
        vk_bytes,
        bundles,
        da: None,
    };

    let mut stdin = SP1Stdin::new();
    stdin.write(&input);

    let client = ProverClient::from_env();
    let t0 = Instant::now();

    if args.execute {
        println!("\n🔍 EXECUTE — đếm cycles...");
        let (public_values, report) = client
            .execute(GUEST_ELF.clone(), stdin)
            .run()
            .expect("execute thất bại");
        let elapsed = t0.elapsed().as_secs_f64();
        let cycles = report.total_instruction_count();
        // SP1 >=4.1.4 cung cấp thông tin prover gas trong ExecutionReport. Đây là một thang đo (proxy)
        // tốt hơn so với số chu kỳ (cycles) để đánh giá chi phí proving vì đã tính đến trọng số của các precompile.
        let prover_gas = report.gas().unwrap_or(0);
        println!("\n──── PHÂN RÃ CYCLES ────\n{}", report);
        let rss = peak_rss_kib();
        let cgroup_current = cgroup_memory_current_bytes();
        let cgroup_peak = cgroup_memory_peak_bytes();
        let throughput_mips = if elapsed > 0.0 {
            cycles as f64 / elapsed / 1_000_000.0
        } else {
            0.0
        };

        println!("📊 TỔNG CYCLES:      {}", cycles);
        println!("📊 CYCLES / bundle:  {}", cycles / batch.max(1) as u64);
        println!("⛽ PROVER GAS:       {}", prover_gas);
        println!("⛽ GAS / bundle:     {}", prover_gas / batch.max(1) as u64);
        println!("⏱️  Execute time:     {:.2}s", elapsed);
        println!("⚡ Throughput:       {:.2} Mcycles/s", throughput_mips);
        println!("🧠 Peak RSS:         {:.2} GiB", rss as f64 / 1048576.0);
        println!(
            "🧠 Cgroup memory:    current {:.2} GiB | peak {:.2} GiB",
            cgroup_current as f64 / 1073741824.0,
            cgroup_peak as f64 / 1073741824.0
        );

        // ── Diễn giải public values — TUYỆT ĐỐI KHÔNG được phép làm mất kết quả đo ──
        // KHÔNG sử dụng `public_values.read()`: hàm đó giả định định dạng bincode và sẽ panic khi
        // buffer rỗng. Hiện tại, guest thực hiện commit bằng cách gọi `commit_slice(&pv.to_packed())`.
        let pv_slice = public_values.as_slice();
        let pv_len = pv_slice.len();
        let pv_parsed = if pv_len == 0 {
            None
        } else {
            PublicValues::from_packed(pv_slice).ok()
        };
        let num_verified_json = match &pv_parsed {
            Some(pv) => pv.num_verified.to_string(),
            None => "null".to_string(),
        };
        let result_ok = matches!(
            &pv_parsed,
            Some(pv)
                if pv.num_verified as usize == batch
                    && pv_len == sp1_shared::PV_PACKED_LEN
        );

        // TIẾN HÀNH GHI TRƯỚC, diễn giải sau.
        if let Some(p) = &args.json {
            append_json(
                p,
                &format!(
                    r#"{{"mode":"execute","ok":{},"run_id":"{}","phase":"{}","ts":{},"batch":{},"distinct":{},"challenges":{},"cycles":{},"cycles_per_bundle":{},"prover_gas":{},"prover_gas_per_bundle":{},"execute_s":{:.2},"throughput_mcycles_s":{:.4},"peak_rss_kib":{},"cgroup_memory_current_bytes":{},"cgroup_memory_peak_bytes":{},"one_bundle_bytes":{},"da_payload_bytes":{},"num_verified":{},"pv_bytes":{},"cfg":{}}}"#,
                    result_ok, args.run_id, args.phase, now_secs(), batch, distinct,
                    num_steps, cycles, cycles / batch.max(1) as u64, prover_gas,
                    prover_gas / batch.max(1) as u64, elapsed, throughput_mips, rss,
                    cgroup_current, cgroup_peak, one_bundle_bytes, da_payload_bytes,
                    num_verified_json, pv_len, cfg
                ),
            );
        }

        match &pv_parsed {
            Some(pv) => {
                println!(
                    "✅ num_verified = {} / {} | new_state_root = 0x{}",
                    pv.num_verified,
                    batch,
                    hex::encode(pv.new_state_root)
                );
                if (pv.num_verified as usize) < batch {
                    eprintln!(
                        "⚠️  {} / {} proof KHÔNG xác minh (verify) thành công trong zkVM.\n\
                         Nguyên nhân phổ biến nhất: tệp vk.bin không khớp với bundle (các bundle được sinh ra\n\
                         từ nhiều lần chạy bundle_gen khác nhau). Vui lòng sử dụng cờ --num-bundles.",
                        batch - pv.num_verified as usize,
                        batch
                    );
                }
            }
            None if pv_len == 0 => {
                eprintln!(
                    "\n⚠️  Guest KHÔNG commit bất kỳ dữ liệu nào (0 byte public values).\n\
                     Tuy nhiên, số chu kỳ (cycles) VẪN được ghi vào JSONL — không mất kết quả đo đạc.\n\
                     Việc guest dừng (halt) với exit-0 mà không thực hiện commit đồng nghĩa với việc nó đã thoát trước bước cuối cùng:\n\
                     hãy kiểm tra xem guest có xảy ra panic/return sớm ở nhánh xác minh (verify) hay không."
                );
            }
            None => {
                eprintln!(
                    "\n⚠️  Public values có độ dài {} byte, không thể đọc theo bố cục chuẩn (packed) 288 byte.\n\
                     Có sự sai lệch định dạng giữa Guest và host? Guest bắt buộc phải dùng `commit_slice(&pv.to_packed())`,\n\
                     KHÔNG được dùng `io::commit(&pv)` (do bincode ghi theo chuẩn little-endian).\n\
                     Tuy nhiên, số chu kỳ (cycles) VẪN được ghi vào JSONL an toàn.",
                    pv_len
                );
            }
        }

        // Một dòng số chu kỳ (cycles) không đi kèm với public values hợp lệ KHÔNG được xem là kết quả benchmark
        // thành công. Dữ liệu JSONL đã được fsync ở trên nhằm phục vụ cho mục đích chẩn đoán, nhưng mã lỗi exit khác 0
        // sẽ buộc các tiến trình sweep/CI dừng việc gán nhãn PASS cho những dữ liệu chưa được kiểm chứng.
        if !result_ok {
            eprintln!(
                "\n❌ EXECUTE INVALID: yêu cầu num_verified={} và public values={} byte.",
                batch,
                sp1_shared::PV_PACKED_LEN
            );
            std::process::exit(4);
        }
    } else {
        println!("\n🔐 LOCAL PROVE — sinh Groth16 proof (Yêu cầu RAM/disk lớn, không sử dụng hosted network)...");
        let pk = client.setup(GUEST_ELF.clone()).expect("setup thất bại");
        // In khóa xác minh (vkey) NGAY SAU khi setup: cần khóa này để triển khai hợp đồng (deploy contract),
        // và không cần phải chờ đến khi hoàn thành lượt prove (có thể mất nhiều giờ) mới biết được.
        println!("🔑 vkey = {}", pk.verifying_key().bytes32());

        let t_prove = Instant::now();
        let proof = client.prove(&pk, stdin).groth16().run().expect("prove thất bại");
        let prove_s = t_prove.elapsed().as_secs_f64();

        let proof_bytes = proof.bytes();
        let pv_bytes = proof.public_values.as_slice().to_vec();
        let vk = pk.verifying_key();
        client.verify(&proof, vk, None).expect("Groth16 verify FAIL");
        let vkey_bytes32 = vk.bytes32();
        let rss = peak_rss_kib();
        let cgroup_current = cgroup_memory_current_bytes();
        let cgroup_peak = cgroup_memory_peak_bytes();

        let pv_parsed = PublicValues::from_packed(&pv_bytes).ok();
        let num_verified_json = match &pv_parsed {
            Some(pv) => pv.num_verified.to_string(),
            None => "null".to_string(),
        };
        let result_ok = matches!(
            &pv_parsed,
            Some(pv)
                if pv.num_verified as usize == batch
                    && pv_bytes.len() == sp1_shared::PV_PACKED_LEN
        );

        println!("✅ Groth16 proof:    {} bytes", proof_bytes.len());
        println!("✅ Public values:    {} bytes", pv_bytes.len());
        println!(
            "✅ EVM calldata:     ~{} bytes (proof + public values)",
            proof_bytes.len() + pv_bytes.len()
        );
        println!("⏱️  Prove time:       {:.1}s", prove_s);
        println!("🧠 Peak RSS:         {:.2} GiB", rss as f64 / 1048576.0);
        println!(
            "🧠 Cgroup memory:    current {:.2} GiB | peak {:.2} GiB",
            cgroup_current as f64 / 1073741824.0,
            cgroup_peak as f64 / 1073741824.0
        );

        // Lưu trữ artifact TRƯỚC KHI kiểm tra định dạng — quá trình tạo proof này tốn hàng giờ đồng hồ,
        // tuyệt đối không được để mất kết quả chỉ vì sai bố cục public values.
        let out = dir.join(format!("groth16_batch{}_{}", batch, args.run_id));
        std::fs::create_dir_all(&out).expect("không tạo được thư mục artifact Groth16");
        std::fs::write(out.join("proof.bin"), &proof_bytes)
            .expect("không ghi được proof.bin");
        std::fs::write(out.join("public_values.bin"), &pv_bytes)
            .expect("không ghi được public_values.bin");
        std::fs::write(out.join("vkey.txt"), vkey_bytes32.as_bytes())
            .expect("không ghi được vkey.txt");
        std::fs::write(out.join("cfg.json"), &cfg)
            .expect("không ghi được cfg.json");
        println!("💾 Đã lưu {} (proof + public_values + vkey + cfg)", out.display());

        let prove_record = format!(
            r#"{{"mode":"prove","ok":{},"run_id":"{}","phase":"{}","ts":{},"batch":{},"distinct":{},"challenges":{},"prove_s":{:.1},"peak_rss_kib":{},"cgroup_memory_current_bytes":{},"cgroup_memory_peak_bytes":{},"groth16_bytes":{},"public_values_bytes":{},"evm_calldata_bytes":{},"one_bundle_bytes":{},"da_payload_bytes":{},"num_verified":{},"pv_bytes":{},"vkey":"{}","cfg":{}}}"#,
            result_ok,
            args.run_id,
            args.phase,
            now_secs(),
            batch,
            distinct,
            num_steps,
            prove_s,
            rss,
            cgroup_current,
            cgroup_peak,
            proof_bytes.len(),
            pv_bytes.len(),
            proof_bytes.len() + pv_bytes.len(),
            one_bundle_bytes,
            da_payload_bytes,
            num_verified_json,
            pv_bytes.len(),
            vkey_bytes32,
            cfg
        );
        std::fs::write(out.join("result.json"), format!("{}\n", prove_record))
            .expect("không ghi được result.json");

        if let Some(p) = &args.json {
            append_json(p, &prove_record);
        }

        // Kiểm tra định dạng SAU KHI đã lưu thành công. Hợp đồng sẽ revert với lỗi BadPublicValuesLength nếu
        // độ dài khác 288; việc phát hiện ngay tại đây ít tốn kém hơn rất nhiều so với việc phát hiện sau khi triển khai (deploy).
        if pv_bytes.len() != sp1_shared::PV_PACKED_LEN {
            eprintln!(
                "\n❌ Public values dài {} byte, nhưng hợp đồng yêu cầu chính xác {} byte.\n\
                 Có phải Guest đang dùng `io::commit(&pv)` thay vì `commit_slice(&pv.to_packed())`?\n\
                 Tuy nhiên, artifact VẪN được lưu an toàn tại {}.",
                pv_bytes.len(),
                sp1_shared::PV_PACKED_LEN,
                out.display()
            );
        } else {
            match &pv_parsed {
                Some(pv) => println!(
                    "✅ Public values hợp lệ: epoch={} num_verified={} new_state_root=0x{}",
                    pv.epoch,
                    pv.num_verified,
                    hex::encode(pv.new_state_root)
                ),
                None => eprintln!("\n❌ Public values có độ dài đúng 256 byte nhưng sai bố cục định dạng."),
            }
        }

        if !result_ok {
            eprintln!(
                "\n❌ PROVE INVALID: proof đã được lưu lại để phục vụ chẩn đoán nhưng không được sử dụng làm benchmark; yêu cầu num_verified={} và public values={} byte.",
                batch,
                sp1_shared::PV_PACKED_LEN
            );
            std::process::exit(5);
        }
    }
}

/// Ghi thêm (append) 1 dòng JSON (JSONL) rồi thực hiện FLUSH + FSYNC — nếu tiến trình bị OOM-kill
/// ngay sau đó, dòng vừa ghi vẫn được đảm bảo nằm an toàn trên đĩa. Các phiên bản trước chỉ dựa vào cơ chế flush-on-drop.
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
