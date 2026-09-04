// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

/// [SPEC §C.2.2] Giao diện bộ xác minh Groth16.
///
/// Trừu tượng hoá để đổi backend mà không đụng EngramManager. Hai hiện thực:
///   - SP1Groth16Verifier  : bộ xác minh thật của SP1
///   - MockVerifier        : dùng khi mô phỏng, chấp nhận mọi bằng chứng
///
/// [SPEC §M.2.2 ②] Đây cũng là chỗ giải bài toán Groth16 OOM: khâu BỌC nằm sau
/// một giao diện với hai hiện thực (cục bộ / mạng chứng minh). Coupling duy nhất
/// là public input 32 byte của ELF, nên đổi backend KHÔNG đụng mạch, KHÔNG đụng
/// hợp đồng, và số 356 B cùng 487.109 gas vẫn dùng được.
interface IEngramVerifier {
    function verifyProof(
        bytes32 programVKey,
        bytes calldata publicValues,
        bytes calldata proofBytes
    ) external view;
}
