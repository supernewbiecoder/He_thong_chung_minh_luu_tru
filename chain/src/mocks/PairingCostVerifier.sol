// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {IEngramVerifier} from "../interfaces/IEngramVerifier.sol";

/// Bộ xác minh chạy ĐÚNG ĐƯỜNG TÍNH TOÁN của Groth16, để đo gas THẬT.
///
/// ── VÌ SAO CẦN, VÀ NÓ KHÔNG PHẢI CÁI GÌ ───────────────────────────────────
///
/// `MockVerifier` chỉ kiểm độ dài rồi trả về, nên gas đo được (244.444) là
/// LOGIC HỢP ĐỒNG, không gồm xác minh. Muốn con số đầy đủ thì phải chạy phép
/// ghép cặp thật.
///
/// Sinh một bằng chứng SP1 hợp lệ cần hàng chục GiB RAM — máy 37 GiB không làm
/// nổi. Nhưng KHÔNG CẦN bằng chứng hợp lệ để đo gas: precompile `ecPairing`
/// tốn ĐÚNG BẰNG NHAU dù kết quả trả về 1 hay 0. Nó làm hết công việc rồi mới
/// so sánh.
///
/// Nên hợp đồng này dùng các điểm sinh G1, G2 — hợp lệ trên đường cong, nên
/// precompile chạy đủ — và bỏ qua kết quả. Đường tính toán giống hệt bộ xác
/// minh thật; chỉ có KẾT LUẬN là vô nghĩa.
///
/// ĐÂY KHÔNG PHẢI bộ xác minh. Nó không chứng minh gì cả. Nó là THƯỚC ĐO.
/// Đừng bao giờ deploy nó ở đâu ngoài môi trường đo đạc.
contract PairingCostVerifier is IEngramVerifier {
    uint256 constant G1_X = 1;
    uint256 constant G1_Y = 2;
    uint256 constant G2_X0 = 0x198e9393920d483a7260bfb731fb5d25f1aa493335a9e71297e485b7aef312c2;
    uint256 constant G2_X1 = 0x1800deef121f1e76426a00665e5c4479674322d4f75edadd46debd5cd992f6ed;
    uint256 constant G2_Y0 = 0x090689d0585ff075ec9e99ad690c3395bc4b313370b38ef355acdadcd122975b;
    uint256 constant G2_Y1 = 0x12c85ea5db8c6deb4aab71808dcb408fe3d1e7690c43d37b4ce6cc0166fa7daa;

    uint256 public lastPairingResult;

    /// Đi đúng ba bước của một bộ xác minh Groth16:
    ///   ① ecMul cho từng public input      6.000 gas mỗi lần
    ///   ② ecAdd gộp lại                      150 gas mỗi lần
    ///   ③ ecPairing 4 cặp                181.000 gas
    function verifyProof(bytes32, bytes calldata publicValues, bytes calldata proofBytes)
        external
    {
        require(proofBytes.length == 356, "do dai bang chung sai");

        // ① + ② gộp public values thành một điểm — SP1 gộp 296 byte thành
        // một băm 32 byte, nên hai phép ecMul là đại diện sát.
        uint256[3] memory mulIn;
        uint256[2] memory acc;
        for (uint256 i = 0; i < 2; i++) {
            mulIn[0] = G1_X;
            mulIn[1] = G1_Y;
            mulIn[2] = uint256(keccak256(abi.encodePacked(publicValues, i)));
            uint256[2] memory p;
            assembly {
                if iszero(staticcall(gas(), 0x07, mulIn, 0x60, p, 0x40)) { revert(0, 0) }
            }
            if (i == 0) {
                acc = p;
            } else {
                uint256[4] memory addIn = [acc[0], acc[1], p[0], p[1]];
                assembly {
                    if iszero(staticcall(gas(), 0x06, addIn, 0x80, acc, 0x40)) { revert(0, 0) }
                }
            }
        }

        // ③ ecPairing 4 cặp — chi phí ÁP ĐẢO, 181.000 gas.
        uint256[24] memory pin;
        for (uint256 i = 0; i < 4; i++) {
            pin[i * 6 + 0] = G1_X;
            pin[i * 6 + 1] = G1_Y;
            pin[i * 6 + 2] = G2_X0;
            pin[i * 6 + 3] = G2_X1;
            pin[i * 6 + 4] = G2_Y0;
            pin[i * 6 + 5] = G2_Y1;
        }
        uint256[1] memory out;
        assembly {
            if iszero(staticcall(gas(), 0x08, pin, 0x300, out, 0x20)) { revert(0, 0) }
        }
        // KHÔNG kiểm out[0]. Bằng chứng ở đây không hợp lệ và không cần hợp lệ —
        // gas đã tiêu hết rồi, và gas mới là thứ đang đo.
        lastPairingResult = out[0];
    }
}
