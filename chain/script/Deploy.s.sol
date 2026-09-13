// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {EngramManager} from "../src/EngramManager.sol";
import {MockVerifier} from "../src/mocks/MockVerifier.sol";
import {MockBlobstream} from "../src/mocks/MockBlobstream.sol";
import {IEngramVerifier} from "../src/interfaces/IEngramVerifier.sol";
import {IBlobstream} from "../src/interfaces/IBlobstream.sol";

/// [CHỐT A2-c] Deploy theo ba chế độ, chọn bằng biến môi trường CHAIN_MODE.
///
///     local | mocha-anvil   → MockVerifier + MockBlobstream
///     mocha-sepolia         → địa chỉ Blobstream THẬT từ biến BLOBSTREAM_ADDR
///
/// Ghi địa chỉ ra out/deployed.addr để docker-compose truyền cho các dịch vụ.
contract Deploy is Script {
    function run() external {
        string memory mode = vm.envOr("CHAIN_MODE", string("local"));

        vm.startBroadcast();

        IEngramVerifier verifier;
        IBlobstream blobstream;

        if (keccak256(bytes(mode)) == keccak256("mocha-sepolia")) {
            // Giai đoạn 3: Blobstream thật. [SPEC docs/KIEM_THU.md]
            verifier = IEngramVerifier(vm.envAddress("VERIFIER_ADDR"));
            blobstream = IBlobstream(vm.envAddress("BLOBSTREAM_ADDR"));
        } else {
            verifier = new MockVerifier();
            blobstream = new MockBlobstream();
        }

        // [SPEC §D.2.2] Hằng số ghim. Ở bản thật, STORAGE_VK_DIGEST phải là băm
        // của tệp vk sinh MỘT LẦN từ SRS lấy ở ceremony công khai — xem §M.2.2 ①.
        // Giá trị dưới đây là giữ chỗ cho mô phỏng.
        EngramManager m = new EngramManager(
            verifier,
            blobstream,
            keccak256("ENGRAM_STORAGE_VK_V1"),
            keccak256("ENGRAM_ACTIVATION_VK_V1"),
            keccak256("ENGRAM_WORKER_PROGRAM_V1"),
            keccak256("ENGRAM_AGGREGATOR_PROGRAM_V1"),
            bytes32(0),        // genesis state root
            // [R7] Tham số lịch nay vào constructor thay vì ghim cứng, để hợp
            // đồng và guest dùng chung một nguồn. Đổi theo hồ sơ đang chạy:
            // production là (48, S_ns), sim là (4, S_ns).
            uint64(vm.envOr("DEADLINES_PER_EPOCH", uint256(48))),
            uint32(vm.envOr("SHARD_COUNT", uint256(10)))
        );

        vm.stopBroadcast();

        console.log("EngramManager:", address(m));
        console.log("che do:", mode);
        vm.writeFile("out/deployed.addr", vm.toString(address(m)));
    }
}
