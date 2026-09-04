// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {IBlobstream} from "../interfaces/IBlobstream.sol";

/// [KHÔNG DÙNG KHI CHẠY THẬT] Blobstream giả.
///
/// [CHỐT — A2-c] Dùng ở chế độ `local` và `mocha-anvil`, nơi không có Blobstream
/// thật. Ở chế độ `mocha-sepolia` thì trỏ vào địa chỉ Blobstream thật.
///
/// Có `setOutage` để kịch bản mô phỏng được sự cố relay treo (§H.1.1): epoch kẹt
/// ở Committed, KHÔNG AI MẤT GÌ, chỉ chưa rút được tiền.
contract MockBlobstream is IBlobstream {
    bool public outage;

    function setOutage(bool v) external { outage = v; }

    function verifyAttestation(uint256, DataRootTuple memory, BinaryMerkleProof memory)
        external view returns (bool)
    {
        return !outage;
    }
}
