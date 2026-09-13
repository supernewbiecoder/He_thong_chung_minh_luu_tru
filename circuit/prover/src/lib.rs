pub mod storage;
pub mod benchmark;
pub mod sealing;
pub mod proving;

pub use benchmark::{ChallengeMetrics, PeakMemoryTracker, ProvingMetrics, SealingMetrics, SetupMetrics, VerificationMetrics};
pub use storage::ProverStorage;
pub use sealing::Sealer;

pub use proving::{EngramStepCircuit, EngramVerifierKey, ProvingPipeline};
// Xuất lại các bí danh kiểu (type aliases) cần thiết cho crate verifier
pub use proving::{G1, G2, SpartanPrimary, SpartanSecondary};