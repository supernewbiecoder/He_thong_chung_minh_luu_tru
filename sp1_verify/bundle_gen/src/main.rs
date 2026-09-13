//! BUNDLE_GEN — Tạo ProofBundle thông qua pipeline Engram và xuất ra tệp tin.
//!
//! TẠI SAO CẦN TÁCH RIÊNG: host (sử dụng sp1-sdk) bị giới hạn với `generic-array =1.1.0`,
//! trong khi nova phiên bản 0.71 yêu cầu `generic-array ^1.2.0`. Hai ràng buộc này không
//! thể cùng tồn tại trong một cây phụ thuộc. Giải pháp là đặt nova tại crate hiện tại
//! (không bao gồm sp1-sdk) và host tại crate kia (không bao gồm nova). Hai tiến trình này
//! giao tiếp thông qua CÁC TỆP TIN (`bundle.bin` và `vk.bin`) thay vì thông qua các kiểu dữ liệu của Rust.
//!
//! Kiến trúc này cũng phản ánh mô hình thực tế: node tạo proof (storage node) và node thực hiện wrap bằng SP1
//! (máy được thuê) là hai tiến trình hoàn toàn độc lập, giao tiếp với nhau qua DA hoặc hệ thống tệp.
//!
//! Lệnh chạy:  `cargo run --release -- --challenges 3 --tree-height 4 --out ../artifacts`
//!
//! ═══════════════════════════════════════════════════════════════════════════
//! ⚠ THAY ĐỔI QUAN TRỌNG: Tùy chọn `--num-bundles` — SỬ DỤNG CHUNG MỘT `PublicParams`
//! ═══════════════════════════════════════════════════════════════════════════
//! VẤN ĐỀ ĐÃ KHẮC PHỤC: Trước đây, mỗi lần thực thi `bundle_gen` sẽ gọi `ProvingPipeline::setup()` một cách độc lập.
//! Tuy nhiên, `PublicParams::setup` KHÔNG mang tính tất định (khi nova được build với feature
//! `test-utils`, commitment key sẽ được tạo ngẫu nhiên). Qua thực nghiệm: khi chạy
//! `bundle_gen` HAI LẦN với CÙNG `--seed 7`, hệ thống sinh ra hai tệp `vk.bin` với mã băm khác biệt:
//!
//!     9f816324825d0d699fa0b783d91b126b45a2ab1f550715146ce1fbb62814350f
//!     d6a2561ba9d7b6f87cf0a76218ed4a6c962c7a219d1c1635973515e45f43a9ad
//!
//! Hệ quả là, nếu tạo N bundle bằng cách chạy N lần vào cùng một thư mục, mỗi lần chạy sẽ GHI ĐÈ
//! lên tệp `vk.bin`. Chỉ có khóa xác minh (vk) của lần chạy cuối cùng được giữ lại, khiến N-1 bundle
//! trước đó không còn vk tương ứng. Khi guest sử dụng sai vk để xác minh, quá trình sẽ thất bại.
//! Đây chính là nguyên nhân khiến việc thử nghiệm với tùy chọn `--distinct-dir` không hoạt động.
//!
//! GIẢI PHÁP: Tạo N bundle trong MỘT tiến trình duy nhất, dùng CHUNG một pipeline. Do đó, toàn bộ N proof
//! sẽ được xác minh thành công bởi cùng một vk — đúng với giả định của kiến trúc Modular-PoSt.
//!
//! ⚠ LƯU Ý: Đây vẫn CHƯA PHẢI là giải pháp hoàn chỉnh cho một hệ thống thực tế, mà chỉ đáp ứng được cho mục đích thử nghiệm.
//! Trong môi trường thực tế, các storage node vận hành trên CÁC MÁY CHỦ KHÁC NHAU nhưng vẫn phải
//! dùng chung một vk. Điều này đồng nghĩa với việc `PublicParams` phải mang tính TẤT ĐỊNH và được công khai —
//! sử dụng `setup_with_ptau_dir()` với tệp Perpetual Powers of Tau cố định và loại bỏ feature
//! `test-utils`. Cho đến khi đạt được điều này, "một vk dùng chung cho mọi node" vẫn chỉ là một
//! GIẢ ĐỊNH CHƯA ĐƯỢC THỎA MÃN. Vấn đề này cần được nêu rõ trong phần Thảo luận về Bảo mật (Security Discussion)
//! của bài báo dưới dạng giả định thiết lập tin cậy (trusted-setup assumption) — chứ không chỉ đơn thuần là một thao tác xử lý kỹ thuật.
//!
//! ── CÁC THAY ĐỔI TRƯỚC ĐÓ (vẫn được giữ nguyên) ──
//! 1. Sử dụng `--tree-height` thay vì gán cứng (hardcode) giá trị `sector_size`. Với `num_chunks` = 2^h, kích thước `sector` = 4KB * 2^h.
//! 2. Sử dụng `--seed` để tạo ra các bundle HOÀN TOÀN KHÁC BIỆT (với các giá trị `replica_id`, `beacon`, và `sector_id` khác nhau).
//! 3. Sử dụng `--json` để ghi lại một dòng JSONL bao gồm toàn bộ cấu hình, thời gian tạo (`gen_s`), và bộ nhớ RSS tối đa (`peak RSS`).
//! 4. Bổ sung `--scratch` và thực hiện xóa sector tạm thời NGAY LẬP TỨC sau khi quá trình thu thập challenge hoàn tất.

use clap::Parser;
use ff::{Field, PrimeField};

use core_primitives::chunking::{bytes_to_fr, bytes_to_limbs};
use core_primitives::config::EngramConfig;
use core_primitives::poseidon2::hash_2;
use core_primitives::Fr;
use prover::{EngramStepCircuit, ProverStorage, ProvingPipeline, Sealer};
use sp1_shared::ProofBundle;

use std::io::Write;
use std::path::{Path, PathBuf};
use std::collections::HashSet;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

#[derive(Parser)]
struct Args {
    #[clap(long, default_value = "3")]
    challenges: usize,

    /// Chiều cao của Merkle tree. Số lượng chunk `num_chunks` = 2^h, kích thước sector `sector_size` = `chunk_size` * 2^h.
    /// Ví dụ: h=4 tương đương 64KB (mức kiểm tra cơ bản). h=18 tương đương 1GB. h=23 tương đương 32GB (cấu hình môi trường thực tế).
    /// CẢNH BÁO: Với giá trị h lớn, cần đảm bảo ổ đĩa được chỉ định bởi `--scratch` có đủ dung lượng trống tương đương kích thước sector.
    #[clap(long, default_value = "4")]
    tree_height: usize,

    #[clap(long, default_value = "4096")]
    chunk_size: usize,

    /// Seed khởi tạo cho bundle ĐẦU TIÊN. Nếu tạo nhiều bundle (`--num-bundles` N), các seed sẽ là seed, seed+1, …, seed+N-1.
    #[clap(long, default_value = "0")]
    seed: u64,

    /// ⚠ Số lượng các bundle RIÊNG BIỆT được tạo ra trong cùng MỘT tiến trình và SỬ DỤNG CHUNG một khóa xác minh (vk).
    ///
    /// Đây là phương pháp CHÍNH XÁC DUY NHẤT để xây dựng batch cho tùy chọn `--distinct-dir` của host.
    /// Việc chạy `bundle_gen` N lần riêng lẻ KHÔNG MANG LẠI KẾT QUẢ TƯƠNG ĐƯƠNG: do mỗi lần chạy sẽ tạo ra một `PublicParams` khác nhau
    /// (do tính ngẫu nhiên của `test-utils`), dẫn đến các vk không đồng nhất.
    ///
    /// Nếu N > 1, các tệp tin sẽ được đặt tên dạng `bundle_00.bin`, `bundle_01.bin`,… (tùy chọn `--bundle-name` sẽ bị bỏ qua).
    #[clap(long, default_value = "1")]
    num_bundles: usize,

    /// Thư mục đích để lưu các tệp `bundle`, `vk.bin`, và `meta.json` (host sẽ đọc dữ liệu từ đây).
    #[clap(long, default_value = "../artifacts")]
    out: String,

    /// Thư mục dùng để lưu trữ tệp sector tạm thời (sẽ bị xóa ngay sau khi thu thập challenge). Mặc định bằng với tùy chọn `--out`.
    /// Trên môi trường máy chủ, nên cấu hình trỏ tới ổ đĩa scratch (tạm thời). KHÔNG NÊN trỏ vào `tmpfs` nếu tham số `tree_height` lớn.
    #[clap(long)]
    scratch: Option<String>,

    /// Tên của tệp bundle trong trường hợp `--num-bundles` bằng 1. Sẽ bị bỏ qua nếu N > 1.
    #[clap(long, default_value = "bundle.bin")]
    bundle_name: String,

    /// Ghi thêm (append) một dòng dữ liệu JSONL chứa các thông số đo lường vào tệp tin này.
    #[clap(long)]
    json: Option<String>,

    /// Định danh duy nhất cho từng lượt chạy (được tạo bởi script `sweep.sh`) — được lưu vào dữ liệu JSONL nhằm phân biệt các lần đo đạc khác nhau.
    #[clap(long, default_value = "na")]
    run_id: String,
}

fn fr_bytes(f: Fr) -> [u8; 32] {
    let mut out = [0u8; 32];
    // `Fr` là một phần tử của trường hữu hạn (finite field), không phải là kiểu mảng byte thông thường. Khi cần
    // ghi ra tệp tin, tuần tự hóa (serialize), hoặc gán vào `ProofBundle`, ta cần phải chuyển đổi phần tử này
    // về định dạng byte chuẩn 32-byte (256-bit). Do đó, hàm `to_repr()` được sử dụng để lấy biểu diễn dữ liệu cố định của phần tử.
    // Đây là phương pháp tiêu chuẩn trong zk-SNARK: các đầu vào công khai (public inputs) và cam kết (commitments) luôn
    // được lưu dưới dạng chuỗi byte, không phụ thuộc vào bộ nhớ cục bộ hay ngôn ngữ lập trình cụ thể.
    out.copy_from_slice(f.to_repr().as_ref());
    out
}
fn string_to_fr(s: &str) -> Fr {
    bytes_to_fr(s.as_bytes())
}
fn poseidon2_chain(vals: &[Fr]) -> Fr {
    let mut acc = Fr::ZERO;
    for v in vals {
        acc = hash_2(acc, *v);
    }
    acc
}
fn derive_challenge_index(beacon: Fr, sector_id: u64, epoch: usize, c: usize, n: usize) -> usize {
    // `beacon` đóng vai trò như một "yếu tố ngẫu nhiên / public salt" cho từng epoch và sector.
    // `sector_id` dùng để phân biệt giữa các sector, `epoch` biểu thị các mốc thời gian khác nhau,
    // và `c` là chỉ số của challenge trong epoch hiện tại. Tất cả những yếu tố này được băm (hash)
    // với nhau thông qua thuật toán Poseidon2 nhằm chọn ra chỉ số (index) của chunk sẽ được dùng để chứng minh.
    //
    // Kết quả thu được: chỉ số challenge `j_i` là một vị trí cụ thể trong sector. Điểm đặc biệt là
    // vị trí này không bị gán cứng (hardcode) mà được tạo ra dựa trên các dữ liệu tham chiếu ngẫu nhiên.
    // Cơ chế này đảm bảo sự khác biệt của các challenge giữa các bundle hoặc epoch, đồng thời
    // ngăn chặn các cuộc tấn công thông qua việc cố tình chọn trước một đường dẫn Merkle (path) giả mạo.
    let seed = poseidon2_chain(&[
        beacon,
        Fr::from(sector_id),
        Fr::from(epoch as u64),
        Fr::from(c as u64),
    ]);
    let j = u64::from_le_bytes(seed.to_repr().as_ref()[0..8].try_into().unwrap());
    (j as usize % n).saturating_add(1)
}

/// Truy xuất giá trị Peak RSS (mức sử dụng RAM tối đa, tính bằng KiB) của tiến trình bằng cách đọc
/// thuộc tính VmHWM từ tệp `/proc/self/status`. Tính năng này chỉ hỗ trợ trên Linux; trả về 0 nếu không khả dụng.
///
/// ⚠ Lưu ý: Giá trị VmHWM KHÔNG bao gồm bộ nhớ `tmpfs` (ví dụ: `/dev/shm`). Nếu container sử dụng shared memory,
/// con số thu được sẽ THẤP HƠN so với lượng bộ nhớ thực tế được cgroup cấp phát qua `--memory`.
/// Để theo dõi chính xác mức đỉnh, cần sử dụng các công cụ như `docker stats`, tránh nội suy hoặc
/// dự đoán giới hạn bộ nhớ N dựa trên trường thông tin này.
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

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Chứa các thông tin công khai của một bundle — cần thiết để xây dựng trạng thái ban đầu (`z0`) ở phía guest.
struct EpochInputs {
    challenges: Vec<EngramStepCircuit>,
    sector_id: u64,
    epoch: usize,
    sealed_root: Fr,
    beacon: Fr,
    replica_id: Fr,
    seal_s: f64,
}

/// Quy trình thực hiện: Ghi tệp sector tạm thời → Thực hiện niêm phong (seal) → Thu thập challenge → XÓA tệp sector tạm thời.
///
/// Hàm này được tách biệt khỏi hàm `main()` để cho phép gọi nhiều lần trong cùng một tiến trình (hỗ trợ tính năng `--num-bundles`).
/// Bằng cách cấp phát các `seed` khác nhau, ta sẽ tạo ra các giá trị `replica_id`, `beacon`, và `sector_id` hoàn toàn độc lập,
/// từ đó tạo ra những bundle thực sự riêng biệt. Tuy nhiên, do CẤU TRÚC (shape) của mạch (circuit) vẫn không đổi,
/// hệ thống có thể chia sẻ và tái sử dụng cùng một `PublicParams`.
fn build_epoch_inputs(
    config: &EngramConfig,
    seed: u64,
    num_chunks: usize,
    scratch: &Path,
) -> EpochInputs {
    let sector_size_bytes = config.sector_size_bytes;
    let path = scratch.join(format!(
        "_sector_tmp_h{}_s{}.bin",
        config.tree_height, seed
    ));

    {
        // Ghi dữ liệu tuần tự theo từng bộ đệm (buffer) 1MiB thay vì cấp phát toàn bộ dung lượng sector trực tiếp vào RAM.
        // Ở phiên bản cũ, việc sử dụng `vec![0u8; sector_size_bytes]` sẽ tiêu tốn 32GB RAM (với h=23), dẫn đến lỗi Out Of Memory (OOM).
        let mut f = std::io::BufWriter::new(
            std::fs::File::create(&path).expect("không tạo được file sector tạm"),
        );
        const BUF: usize = 1 << 20;
        let mut buf = vec![0u8; BUF];
        let mut written = 0usize;
        while written < sector_size_bytes {
            let n = BUF.min(sector_size_bytes - written);
            for (k, b) in buf[..n].iter_mut().enumerate() {
                // Giữ NGUYÊN công thức cũ để chuỗi byte (byte-stream) được đồng nhất: (i*31 % 251)
                *b = ((written + k) * 31 % 251) as u8;
            }
            f.write_all(&buf[..n]).expect("ghi sector tạm lỗi");
            written += n;
        }
        f.flush().expect("flush sector tạm lỗi");
    }
    println!("📄 sector tạm: {}", path.display());

    // `replica_id` định danh duy nhất cho kho lưu trữ (storage replica) hoặc node đang thực hiện thao tác niêm phong (seal).
    // Đây không phải là một challenge ngẫu nhiên, mà là "định danh" cố định của bản sao: với cùng một dữ liệu sector,
    // nếu người sở hữu (owner) hoặc node khác nhau, `replica_id` sẽ khác nhau, dẫn đến kết quả Merkle tree, commitment
    // và witness cũng khác nhau.
    //
    // Tại đây, giá trị này được sinh ra từ chuỗi "sp1-host-replica-{seed}" và được chuyển hóa thành phần tử `Fr`
    // thông qua thao tác băm (hash) mảng byte của chuỗi đó. Bằng cách sử dụng các giá trị seed khác nhau cho mỗi bundle,
    // hệ thống đảm bảo rằng mỗi bundle đóng vai trò như một bản sao độc lập, mặc dù chúng chia sẻ cùng một cấu trúc mạch
    // và có thể sử dụng chung khóa cấu hình `PublicParams`.
    let replica_id = bytes_to_fr(format!("sp1-host-replica-{}", seed).as_bytes());
    let sealer = Sealer::new(config.clone());
    let mut storage = ProverStorage::new();
    let t_seal = Instant::now();
    sealer.seal_sector_streaming(replica_id, &path, &mut storage);
    let seal_s = t_seal.elapsed().as_secs_f64();
    let sealed_root = storage.merkle_tree.as_ref().unwrap().root;
    println!("🔒 seal xong sau {:.1}s", seal_s);

    let epoch = 0usize;
    // `sector_id` đại diện cho định danh logic của một sector trên storage node. Nó không phản ánh bản sao của tệp sector,
    // mà được dùng để định danh sector trong toàn hệ thống. Trong trường hợp này, ID được gán theo seed
    // để mỗi bundle sở hữu một `sector_id` riêng biệt.
    let sector_id = 7u64 + seed;
    // `beacon` đóng vai trò như một nguồn ngẫu nhiên công khai (public randomness / salt) của epoch/sector,
    // được dùng để cấu hình challenge. Phương pháp này tương tự như khái niệm "beacon" trong các giao thức mã hóa:
    // mỗi sector được cấp một beacon độc lập, và thông qua chuỗi tham số (beacon + sector_id + epoch + challenge index)
    // để xác định chính xác vị trí của chunk cần chứng minh.
    //
    // Việc thay đổi tham số `seed`, `replica_id` hoặc `beacon` sẽ tạo ra một bộ nhân chứng (witness) hoàn toàn khác biệt,
    // ngay cả khi cấu trúc mạch được giữ nguyên. Cơ chế này đảm bảo tính duy nhất và tách biệt của từng bundle,
    // đồng thời cho phép tất cả các proof được xác minh thành công bằng cùng một khóa `verification key`.
    let beacon = string_to_fr(&format!("sp1-host-beacon-{}", seed));

    let mut challenges = Vec::new();
    for c in 1..=config.challenges_per_epoch {
        // Mỗi challenge sẽ được xác định dựa trên công thức sau:
        //   j_i = derive_challenge_index(beacon, sector_id, epoch, c, num_chunks)
        //
        // Thay vì duyệt qua các challenge theo tuần tự, vị trí của chúng được phân bổ ngẫu nhiên dựa vào
        // thông số `beacon`. Phương pháp này hoạt động tương tự như khái niệm "challenge sampling" (lấy mẫu ngẫu nhiên)
        // trong các hệ thống chứng minh: do cả người xác minh (verifier) và người chứng minh (prover) đều
        // chia sẻ chung một seed/beacon, chỉ những vị trí được sinh ra từ công thức này mới được coi là hợp lệ.
        let j_i = derive_challenge_index(beacon, sector_id, epoch, c, num_chunks);
        let raw = storage
            .get_raw_chunk(j_i)
            .expect("get_raw_chunk trả None — sector tạm bị xoá quá sớm?");
        let mp = storage.merkle_tree.as_ref().unwrap().generate_proof(j_i - 1);
        challenges.push(EngramStepCircuit {
            epoch,
            sector_id: Fr::from(sector_id),
            sealed_root,
            beacon,
            j_i,
            s_ji_minus_1: *storage.get_state(j_i - 1).unwrap(),
            s_ji: *storage.get_state(j_i).unwrap(),
            replica_id,
            path_ji_siblings: mp.siblings,
            path_ji_indices: mp.path_indices,
            tree_height: config.tree_height,
            chunk_limbs: bytes_to_limbs(&raw),
            chunk_size_bytes: config.chunk_size_bytes,
        });
    }

    // Xóa tệp an toàn: mọi chunk cần thiết đã được trích xuất và lưu trữ vào mảng `challenges`.
    match std::fs::remove_file(&path) {
        Ok(()) => println!(
            "🧹 đã xoá sector tạm (giải phóng {:.2} MiB đĩa)",
            sector_size_bytes as f64 / 1048576.0
        ),
        Err(e) => eprintln!("⚠️  không xoá được sector tạm {}: {}", path.display(), e),
    }

    EpochInputs {
        challenges,
        sector_id,
        epoch,
        sealed_root,
        beacon,
        replica_id,
        seal_s,
    }
}

fn main() {
    let args = Args::parse();

    // Tham số `num_chunks` BẮT BUỘC phải bằng 2^tree_height. Nếu không, độ dài của Merkle path
    // sẽ bị tính toán sai, dẫn đến hàm `generate_proof()` sinh ra một đường dẫn không khớp với thiết kế của mạch.
    // Giá trị này được tự động suy diễn thay vì để người dùng chỉ định thủ công nhằm tránh các xung đột dữ liệu.
    let num_chunks = 1usize << args.tree_height;
    let sector_size_bytes = args.chunk_size * num_chunks;

    if args.challenges > num_chunks {
        eprintln!(
            "❌ challenges ({}) > num_chunks ({}) — tăng --tree-height hoặc giảm --challenges.",
            args.challenges, num_chunks
        );
        std::process::exit(2);
    }
    if args.num_bundles == 0 {
        eprintln!("❌ --num-bundles phải ≥ 1");
        std::process::exit(2);
    }

    let config = EngramConfig {
        sector_size_bytes,
        chunk_size_bytes: args.chunk_size,
        tree_height: args.tree_height,
        challenges_per_epoch: args.challenges,
        epochs_per_window: 1,
    };

    println!(
        "⚙️  config: tree_height={} num_chunks={} sector={:.2} MiB chunk={}B challenges={} seed={} num_bundles={}",
        args.tree_height,
        num_chunks,
        sector_size_bytes as f64 / 1048576.0,
        args.chunk_size,
        args.challenges,
        args.seed,
        args.num_bundles
    );
    if args.num_bundles > 1 {
        println!(
            "🔗 {} bundle phân biệt, DÙNG CHUNG một PublicParams → cùng một vk.bin",
            args.num_bundles
        );
    }

    let t_all = Instant::now();

    let scratch = PathBuf::from(args.scratch.clone().unwrap_or_else(|| args.out.clone()));
    std::fs::create_dir_all(&scratch).expect("không tạo được thư mục scratch");
    std::fs::create_dir_all(&args.out).expect("không tạo được thư mục out");
    let out = PathBuf::from(&args.out);
    let mut seen_proof_fingerprints: HashSet<u64> = HashSet::new();

    // ── Thực hiện quá trình Thiết lập (Setup) DUY NHẤT MỘT LẦN cho toàn bộ N bundle ────────
    // Sử dụng bundle đầu tiên làm cấu trúc mẫu. Do `PublicParams` chỉ phụ thuộc vào CẤU TRÚC mạch
    // (bao gồm tree_height, chunk_size, và arity) mà không phụ thuộc vào dữ liệu của bộ nhân chứng (witness),
    // một pipeline duy nhất có thể được tái sử dụng để tạo proof cho mọi seed ngẫu nhiên.
    println!("⏳ Sinh CompressedSNARK ({} challenges)...", args.challenges);
    let mut first = build_epoch_inputs(&config, args.seed, num_chunks, &scratch);
    let (pipeline, _setup_metrics) = ProvingPipeline::setup(first.challenges[0].clone());

    let mut total_proof_bytes = 0usize;
    let mut total_fold_s = 0.0f64;
    let mut written: Vec<String> = Vec::new();

    for i in 0..args.num_bundles {
        let seed = args.seed + i as u64;
        let inputs = if i == 0 {
            // Đã được khởi tạo trước đó và dùng làm khuôn mẫu cho quá trình thiết lập — sử dụng lại dữ liệu này thay vì tái tạo.
            EpochInputs {
                challenges: std::mem::take(&mut first.challenges),
                ..first
            }
        } else {
            println!("── bundle {}/{} (seed={}) ──", i + 1, args.num_bundles, seed);
            build_epoch_inputs(&config, seed, num_chunks, &scratch)
        };

        let t_prove = Instant::now();
        let num_steps = inputs.challenges.len();
        let (proof, z0, _m) = pipeline.prove_epoch(inputs.challenges);
        let fold_s = t_prove.elapsed().as_secs_f64();
        total_fold_s += fold_s;

        // Thực hiện Verify NGAY LẬP TỨC trên máy chủ (host): Việc phát hiện và xử lý lỗi tại giai đoạn này
        // tiết kiệm chi phí hơn rất nhiều so với việc phát hiện lỗi sau 20 phút xử lý (execute) trong zkVM.
        proof
            .verify(&pipeline.vk, num_steps, &z0)
            .expect("proof phải verify PASS trên host trước khi ghi");

        let bundle = ProofBundle {
            sector_id: inputs.sector_id,
            epoch: inputs.epoch as u64,
            sealed_root: fr_bytes(inputs.sealed_root),
            beacon: fr_bytes(inputs.beacon),
            replica_id: fr_bytes(inputs.replica_id),
            num_steps: num_steps as u32,
            proof_bytes: bincode::serialize(&proof).unwrap(),
        };
        let proof_bytes_len = bundle.proof_bytes.len();
        total_proof_bytes += proof_bytes_len;

        let mut hasher = DefaultHasher::new();
        bundle.proof_bytes.hash(&mut hasher);
        let proof_fp = hasher.finish();
        if !seen_proof_fingerprints.insert(proof_fp) {
            eprintln!(
                "⚠️  duplicate proof fingerprint {:016x} ở bundle {} (seed={})",
                proof_fp,
                i,
                seed
            );
        }

        // Nếu số lượng bundle (N) > 1 → định dạng tên tệp dựa trên chỉ số (index) nhằm hỗ trợ máy chủ quét dữ liệu qua tùy chọn `--distinct-dir`.
        let name = if args.num_bundles > 1 {
            format!("bundle_{:02}.bin", i)
        } else {
            args.bundle_name.clone()
        };
        let bundle_path = out.join(&name);
        std::fs::write(&bundle_path, bincode::serialize(&bundle).unwrap()).unwrap();
        written.push(name.clone());
        println!(
            "✅ verify PASS → {} | proof={}B | fp={:016x} | fold {:.1}s",
            name, proof_bytes_len, proof_fp, fold_s
        );

        if let Some(p) = &args.json {
            let line = format!(
                r#"{{"mode":"bundle_gen","run_id":"{}","ts":{},"challenges":{},"tree_height":{},"num_chunks":{},"sector_size_bytes":{},"seed":{},"bundle_index":{},"num_bundles":{},"shared_vk":{},"num_steps":{},"seal_s":{:.2},"fold_s":{:.2},"bundle_bytes":{},"peak_rss_kib":{}}}"#,
                args.run_id, now_secs(), args.challenges, args.tree_height, num_chunks,
                sector_size_bytes, seed, i, args.num_bundles,
                // ★ Thiết lập thuộc tính "shared_vk" bằng true CHỈ ÁP DỤNG KHI khởi tạo nhiều bundle
                //   trong cùng một tiến trình — lúc này các bundle sẽ sử dụng chung một khóa vk. Ở phiên bản trước,
                //   giá trị này bị gán cứng là `true`, vô tình biến các lớp bảo vệ bên phía host thành thao tác vô nghĩa (no-op),
                //   làm mất khả năng ngăn chặn các lỗi phát sinh.
                args.num_bundles > 1, num_steps,
                inputs.seal_s, fold_s, proof_bytes_len, peak_rss_kib()
            );
            append_json(p, &line);
        }
    }

    // ── Tệp `vk.bin` chỉ được lưu MỘT LẦN DUY NHẤT và tái sử dụng cho tất cả các bundle vừa được sinh ra ──────────
    std::fs::write(
        out.join("vk.bin"),
        bincode::serialize(&pipeline.vk).unwrap(),
    )
    .unwrap();

    // Tệp `meta.json`: chứa các cấu hình liên kết với artifact. Nếu thiếu tệp này,
    // sau một thời gian, sẽ không ai có thể xác định được `bundle.bin` lưu trong bộ nhớ cache
    // đã được khởi tạo với tham số `tree_height` là bao nhiêu.
    let meta = format!(
        r#"{{"tree_height":{},"num_chunks":{},"sector_size_bytes":{},"chunk_size_bytes":{},"challenges":{},"seed":{},"num_bundles":{},"shared_vk":{},"num_steps":{},"proof_bytes":{},"nova":"0.71.1","generated_at":{}}}"#,
        args.tree_height,
        num_chunks,
        sector_size_bytes,
        args.chunk_size,
        args.challenges,
        args.seed,
        args.num_bundles,
        args.num_bundles > 1,
        args.challenges,
        total_proof_bytes / args.num_bundles.max(1),
        now_secs()
    );
    std::fs::write(out.join("meta.json"), &meta).ok();

    let gen_s = t_all.elapsed().as_secs_f64();
    println!(
        "💾 Đã ghi {} bundle + vk.bin + meta.json vào {} | tổng proof={}B | fold {:.1}s | tổng {:.1}s | peak RSS {:.2} GiB",
        written.len(),
        out.display(),
        total_proof_bytes,
        total_fold_s,
        gen_s,
        peak_rss_kib() as f64 / 1048576.0
    );

    if args.num_bundles > 1 {
        println!(
            "   → chạy host ĐỐI CHỨNG: engram-host --execute --artifacts {} --distinct-dir {}",
            args.out, args.out
        );
    } else {
        println!(
            "   → giờ chạy host: engram-host --execute --artifacts {}",
            args.out
        );
    }
}

/// Ghi bổ sung (append) 1 dòng định dạng JSONL, sau đó thực hiện lệnh FLUSH và FSYNC.
/// Việc gọi `fsync` đảm bảo rằng nếu tiến trình vô tình bị đóng bởi hệ thống do hết bộ nhớ (OOM-kill),
/// dữ liệu vừa ghi vẫn tồn tại an toàn trên ổ đĩa và không bị thất thoát.
fn append_json(path: &str, line: &str) {
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .expect("không mở được file json");
    writeln!(f, "{}", line).expect("ghi json lỗi");
    f.flush().ok();
    f.sync_all().ok();
    println!("📝 Đã ghi số liệu vào {}", path);
}