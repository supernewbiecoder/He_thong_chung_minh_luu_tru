use std::time::Instant;

// Loại bỏ các import không sử dụng (`ipa_pc::EvaluationEngine`, `PallasEngine`, `VestaEngine`).
// Crate này sử dụng `Bn256EngineKZG` và `GrumpkinEngine` thông qua `prover::{G1, G2}`.
// Việc loại bỏ các tàn dư từ hệ thống đường cong Pallas/Vesta giúp giảm cảnh báo và tránh gây nhầm lẫn về hệ thống đường cong đang được sử dụng.
use nova_snark::{
    nova::{CompressedSNARK, PublicParams},
    traits::Engine,
};
use prover::{EngramStepCircuit, EngramVerifierKey};
use prover::{G1, G2, SpartanPrimary, SpartanSecondary};
use prover::{PeakMemoryTracker, VerificationMetrics};
use prover::benchmark::elapsed_ms_f64;

type NovaFr = <G1 as Engine>::Scalar;

pub struct EngramVerifier;

impl EngramVerifier {
    /// Xác minh bằng chứng Spartan.
    /// Hàm này nhận vào `Verification Key` (`vk`) đã được lưu trữ từ `ProvingPipeline` 
    /// thay vì gọi lại `CompressedSNARK::setup()`, giúp tiết kiệm thời gian và đảm bảo độ chính xác của các chỉ số hiệu suất.
    ///
    /// Trong trường hợp hệ thống gọi không có sẵn `vk` (ví dụ: các trình xác minh độc lập hoặc on-chain),
    /// có thể truyền giá trị `None`. Khi đó, hàm sẽ tự động tạo `vk` từ tham số công khai (`pp`). 
    /// Lưu ý rằng quá trình này sẽ tiêu tốn thêm thời gian và sẽ được ghi nhận vào `vk_setup_ms`.
    pub fn verify_proof(
        pp: &PublicParams<G1, G2, EngramStepCircuit>,
        proof: &CompressedSNARK<G1, G2, EngramStepCircuit, SpartanPrimary, SpartanSecondary>,
        num_steps: usize,
        z0_primary: Vec<NovaFr>,
        vk_opt: Option<&EngramVerifierKey>,
    ) -> (bool, VerificationMetrics) {
        println!("========================================================");
        println!("🔍 [VERIFIER] Bắt đầu xác minh bằng chứng Spartan...");

        let mut metrics = VerificationMetrics::default();
        let mut peak = PeakMemoryTracker::new();

        // Sử dụng `vk` được truyền vào nếu có. Ngược lại, tạo `vk` mới từ `pp` (quá trình này sẽ tốn thêm thời gian thực thi).
        let vk_setup_start = Instant::now();
        let derived_vk;
        let vk = match vk_opt {
            Some(v) => v,
            None => {
                let (_pk, v) = CompressedSNARK::<G1, G2, EngramStepCircuit, SpartanPrimary, SpartanSecondary>::setup(pp).unwrap();
                derived_vk = v;
                &derived_vk
            }
        };
        metrics.vk_setup_ms = elapsed_ms_f64(vk_setup_start);
        peak.sample();

        let start = Instant::now();
        let verification_result = proof.verify(vk, num_steps, &z0_primary);
        let verify_time = elapsed_ms_f64(start);

        println!("⏱️  Metric - Verify Time (verify_time): {:.3} ms", verify_time);
        metrics.verify_time_ms = verify_time;
        metrics.ram_peak_kib = peak.peak_kib();

        let is_valid = match verification_result {
            Ok(zn_primary) => {
                println!("✅ KẾT QUẢ: Bằng chứng HỢP LỆ!");
                println!("   -> Trạng thái tích lũy cuối cùng (z_n): {:?}", zn_primary[0]);
                true
            }
            Err(e) => {
                println!("❌ KẾT QUẢ: Bằng chứng KHÔNG HỢP LỆ!");
                println!("   -> Lỗi từ hệ thống chứng minh: {:?}", e);
                false
            }
        };

        (is_valid, metrics)
    }
}
