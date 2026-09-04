// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {IEngramVerifier} from "../interfaces/IEngramVerifier.sol";

/// [KHÔNG DÙNG KHI CHẠY THẬT] Bộ xác minh giả cho mô phỏng.
///
/// [CHỐT — quyết định D3] Bản hiện thực dùng MÔ HÌNH CHI PHÍ: bằng chứng là đối
/// tượng giả có ĐÚNG KÍCH THƯỚC thật (356 B), nên calldata và gas là THẬT. Chỉ
/// nội dung mật mã là giả.
///
/// Nó vẫn kiểm ĐỘ DÀI bằng chứng, vì độ dài là thứ ảnh hưởng tới gas — và gas
/// mới là con số bài báo tuyên bố.
contract MockVerifier is IEngramVerifier {
    uint256 public constant GROTH16_PROOF_BYTES = 356;

    error BadProofLength();

    function verifyProof(bytes32, bytes calldata, bytes calldata proofBytes) external pure {
        if (proofBytes.length != GROTH16_PROOF_BYTES) revert BadProofLength();
    }
}
