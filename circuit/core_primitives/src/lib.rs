pub mod config;
pub mod poseidon2;
pub mod poseidon2_gadget;
pub mod merkle_tree;
pub mod chunking;

// Cung cấp lại (re-export) các thành phần chính nhằm đơn giản hóa việc tích hợp và sử dụng từ các crate khác.
pub use config::EngramConfig;
pub use chunking::{bytes_to_fr, bytes_to_limbs, fold_limbs, num_limbs, LIMB_BYTES};
pub use nova_snark::provider::bn256_grumpkin::bn256::Scalar as Fr;