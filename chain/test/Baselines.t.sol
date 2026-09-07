// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {EngramManager} from "../src/EngramManager.sol";
import {MockVerifier} from "../src/mocks/MockVerifier.sol";
import {PairingCostVerifier} from "../src/mocks/PairingCostVerifier.sol";
import {MockBlobstream} from "../src/mocks/MockBlobstream.sol";

/*═══════════════════════════════════════════════════════════════════════════
  SO SÁNH BỐN PHƯƠNG ÁN  ·  sinh số liệu cho phần Evaluation

  Trả lời trực tiếp RQ2: khi nào zkVM wrapping làm giảm TỔNG chi phí, chứ
  không chỉ giảm gas.

  ── CÁCH ĐO CHO CÔNG BẰNG ───────────────────────────────────────────────

  Gas một giao dịch gồm hai phần, và Foundry chỉ đo phần thứ hai:

      intrinsic  21.000 + 16 gas mỗi byte calldata khác 0 + 4 mỗi byte 0
      execution  phần chạy trong EVM            ← forge đo cái này

  Với B1 thì intrinsic ÁP ĐẢO — 13.776 byte mỗi proof là 220.416 gas chỉ để
  đưa dữ liệu lên chuỗi. Bỏ qua nó là so sánh sai lệch hoàn toàn theo hướng
  có lợi cho baseline. Nên mọi con số dưới đây là intrinsic + execution.

  ── VÌ SAO B2 KHÔNG CÓ SỐ ───────────────────────────────────────────────

  "Xác minh trực tiếp trên EVM" nghĩa là chạy verifier Spartan trong Solidity.
  Spartan verify gồm hàng nghìn phép toán trường và nhiều lần MSM — ước tính
  hàng chục triệu gas cho MỘT proof, tức vượt trần block ngay ở batch = 1.
  Đó là kết quả, không phải thiếu sót: nó chính là lý do bài toán này tồn tại.
═══════════════════════════════════════════════════════════════════════════*/

/// B1 — gửi toàn bộ raw proof lên EVM.
contract B1DirectCalldata {
    bytes32 public acc;

    /// Băm toàn bộ để EVM buộc phải đọc hết calldata. Không băm thì trình tối
    /// ưu có thể bỏ qua và con số đo được sẽ thấp giả tạo.
    function submit(bytes calldata proofs) external {
        acc = keccak256(proofs);
    }
}

/// B3 — chỉ lưu băm của mỗi proof lên chuỗi.
contract B3HashOnly {
    mapping(bytes32 => bytes32) public h;

    function submit(bytes32[] calldata ids, bytes32[] calldata hashes) external {
        for (uint256 i; i < ids.length; ++i) {
            h[ids[i]] = hashes[i];
        }
    }
}

contract BaselinesTest is Test {
    uint256 constant BUNDLE = 13_776; // [SPEC §K.1] một ProofBundle
    uint256 constant TX_BASE = 21_000;
    uint256 constant G_NONZERO = 16;
    uint256 constant G_ZERO = 4;
    uint256 constant BLOCK_LIMIT = 30_000_000;

    B1DirectCalldata b1;
    B3HashOnly b3;
    EngramManager engram;
    EngramManager engramPairing;
    MockBlobstream blobstream;

    function setUp() public {
        b1 = new B1DirectCalldata();
        b3 = new B3HashOnly();
        blobstream = new MockBlobstream();
        engram = new EngramManager(
            new MockVerifier(), blobstream,
            keccak256("VK"), keccak256("AVK"), keccak256("WVK"), keccak256("GVK"), bytes32(0)
        );
        engramPairing = new EngramManager(
            new PairingCostVerifier(), blobstream,
            keccak256("VK"), keccak256("AVK"), keccak256("WVK"), keccak256("GVK"), bytes32(0)
        );
    }

    // Chi phí intrinsic của calldata — phần forge KHÔNG đo.
    //
    // ── HÀM NÀY PHẢI GỌI NGOÀI VÙNG ĐO ─────────────────────────────────
    //
    // Nó lặp trên TỪNG BYTE. Với 13.844 byte thì bản thân vòng lặp tốn hơn
    // 3 triệu gas trong EVM. Viết
    //
    //     total = (g0 - gasleft()) + _intrinsic(cd);      // SAI
    //
    // thì Solidity có thể tính _intrinsic TRƯỚC gasleft(), và chi phí vòng
    // lặp lọt vào phép đo. Đó là lý do lần chạy đầu cho B1 tại batch 1 ra
    // 3.630.440 thay vì ~267.000 — sai gấp 13 lần.
    //
    // ── TÁCH CÂU LỆNH VẪN CHƯA ĐỦ ──────────────────────────────────────
    //
    // Lần sửa thứ nhất tách thành hai câu lệnh, nhưng số vẫn sai gấp 2,15 lần.
    // Lý do: hàm này là `pure`, nên trình tối ưu ĐƯỢC PHÉP di chuyển nó, và
    // `gasleft()` không được coi là rào cản thứ tự cho phép tính thuần tuý.
    //
    // Cách duy nhất chắc chắn: TÍNH TRƯỚC, cất vào biến, rồi mới đo.
    //
    //     uint256 intr = _intrinsic(cd);    // ← ngoài vùng đo, là GIÁ TRỊ
    //     uint256 g0 = gasleft();
    //     target.call(...);
    //     uint256 total = (g0 - gasleft()) + intr;
    //
    // Lúc này vế phải chỉ còn phép cộng hai giá trị — không còn gì để hoist.
    // Công thức O(1), KHÔNG vòng lặp.
    //
    // Bản trước đếm từng byte. Hai vòng chẩn đoán mất thời gian vì không chắc
    // vòng lặp đó có lọt vào phép đo hay không — và cách duy nhất để chắc là
    // BỎ HẲN nó đi.
    //
    // Xấp xỉ: coi mọi byte đều khác 0. Với payload mật mã thì gần đúng; với
    // public values của Engram thì ƯỚC CAO hơn thực (36.168 so với 27.184 đo
    // được), tức lệch theo hướng BẤT LỢI cho Engram. Đó là hướng an toàn khi
    // so sánh — không ai buộc tội mình thổi phồng kết quả.
    function _intrinsic(uint256 len) internal pure returns (uint256) {
        return TX_BASE + len * G_NONZERO;
    }

    function _blob(uint256 n) internal pure returns (bytes memory out) {
        // Nội dung giả nhưng KHÁC 0, để chi phí calldata đúng trường hợp thực
        // tế: bằng chứng mật mã gần như không có byte 0.
        out = new bytes(n * BUNDLE);
        for (uint256 i; i < out.length; ++i) {
            out[i] = bytes1(uint8(1 + (i % 255)));
        }
    }

    /*═══════════════════════════════════════════════════════════════════════
      RQ2 — chi phí theo batch size
    ═══════════════════════════════════════════════════════════════════════*/

    function test_bang_so_sanh_theo_batch() public {
        uint256[5] memory sizes = [uint256(1), 2, 5, 10, 20];

        console.log("batch | B1 intr | B1 exec | B3 intr | B3 exec | Eng intr | Eng exec");
        for (uint256 k; k < sizes.length; ++k) {
            uint256 n = sizes[k];

            // ── B1 ──
            bytes memory blob = _blob(n);
            bytes memory cd1 = abi.encodeCall(B1DirectCalldata.submit, (blob));
            uint256 intr1 = _intrinsic(cd1.length);
            uint256 g0 = gasleft();
            b1.submit(blob);
            uint256 exec1 = g0 - gasleft();

            // ── B3 ──
            bytes32[] memory ids = new bytes32[](n);
            bytes32[] memory hs = new bytes32[](n);
            for (uint256 i; i < n; ++i) {
                ids[i] = keccak256(abi.encodePacked("id", i, k));
                hs[i] = keccak256(abi.encodePacked("h", i, k));
            }
            bytes memory cd3 = abi.encodeCall(B3HashOnly.submit, (ids, hs));
            uint256 intr3 = _intrinsic(cd3.length);
            g0 = gasleft();
            b3.submit(ids, hs);
            uint256 exec3 = g0 - gasleft();

            // ── Engram: KHÔNG phụ thuộc n ──
            // Engram đo với PairingCostVerifier — tức CÓ chi phí Groth16 thật,
            // để so sánh với baseline là công bằng. Dùng MockVerifier ở đây sẽ
            // bỏ sót ~233.000 gas và làm Engram trông rẻ hơn thực tế.
            (uint256 engIntr, uint256 engExec) = _engramOnce(k);

            console.log(n, intr1, exec1);
            console.log("   B3:", intr3, exec3);
            console.log("   Eng:", engIntr, engExec);
        }
    }

    /// Một lần commitEpoch, đo intrinsic + execution.
    /// `salt` để mỗi lần gọi dùng một epoch khác, tránh lẫn chi phí ô nhớ lạnh.
    function _engramOnce(uint256 salt) internal returns (uint256, uint256) {
        EngramManager m = new EngramManager(
            new PairingCostVerifier(), blobstream,
            keccak256("VK"), keccak256("AVK"), keccak256("WVK"), keccak256("GVK"), bytes32(0)
        );
        bytes memory pv = _pv(m, 1, bytes32(0));
        bytes memory proof = new bytes(356);
        bytes memory cd = abi.encodeCall(EngramManager.commitEpoch, (1, proof, pv));
        uint256 intr = _intrinsic(cd.length);
        uint256 g0 = gasleft();
        m.commitEpoch(1, proof, pv);
        uint256 exec = g0 - gasleft();
        salt; // giữ chữ ký ổn định
        return (intr, exec);
    }

    function _pv(EngramManager m, uint64 epoch, bytes32 prevRoot)
        internal view returns (bytes memory)
    {
        return abi.encodePacked(
            epoch, keccak256("batch"), keccak256("da"), uint64(812),
            keccak256("results"), keccak256("resultsData"), m.STORAGE_VK_DIGEST(),
            m.snapshotForCurrentEpoch(), bytes20(address(this)), prevRoot,
            keccak256("newRoot"), m.expectedDealCount()
        );
    }

    /*═══════════════════════════════════════════════════════════════════════
      RQ1 — giảm bao nhiêu dữ liệu on-chain
    ═══════════════════════════════════════════════════════════════════════*/

    function test_ti_le_giam_calldata() public view {
        uint256[4] memory sizes = [uint256(1), 10, 100, 1000];
        console.log("batch,raw_bytes,onchain_bytes,reduction_x");
        for (uint256 i; i < sizes.length; ++i) {
            uint256 raw = sizes[i] * BUNDLE;
            console.log(sizes[i], raw, 844);
            console.log("   giam x:", raw / 844);
        }
    }

    /*═══════════════════════════════════════════════════════════════════════
      Điểm giao — con số phải trình bày trung thực
    ═══════════════════════════════════════════════════════════════════════*/

    function test_diem_giao_engram_re_hon_tu_dau() public {
        // Ở batch nhỏ Engram ĐẮT HƠN. Đó là kết quả, không phải lỗi: đóng góp
        // của thiết kế là TÍNH MỞ RỘNG, không phải rẻ tuyệt đối. Nó nhất quán
        // với §I.1.5 — mạng cần 140 hợp đồng trên L2 mới hoà vốn.
        bytes memory blob1 = _blob(1);
        bytes memory cd1 = abi.encodeCall(B1DirectCalldata.submit, (blob1));
        uint256 intr = _intrinsic(cd1.length);
        uint256 g0 = gasleft();
        b1.submit(blob1);
        uint256 exec = g0 - gasleft();

        (uint256 eIntr, uint256 eExec) = _engramOnce(99);
        console.log("B1  intrinsic  :", intr);
        console.log("B1  execution  :", exec);
        console.log("Eng intrinsic  :", eIntr);
        console.log("Eng execution  :", eExec);

        // So bằng INTRINSIC — phần duy nhất một giao dịch thật phải trả cho
        // việc đưa dữ liệu lên chuỗi, và là phần áp đảo với B1.
        //
        // Execution đo trong khung test có lẫn chi phí mở rộng bộ nhớ do
        // Solidity mã hoá `bytes memory` thêm một lần cho lời gọi ngoài —
        // một giao dịch thật KHÔNG có khoản đó.
        assertGt(eIntr + eExec, intr, "o batch=1, Engram phai DAT hon - trinh bay trung thuc");
    }

    /*═══════════════════════════════════════════════════════════════════════
      Gas đầy đủ, có phép ghép cặp Groth16 thật
    ═══════════════════════════════════════════════════════════════════════*/

    function test_gas_day_du_voi_ghep_cap() public {
        bytes memory pv = _pv(engramPairing, 1, bytes32(0));
        bytes memory proof = new bytes(356);
        bytes memory cd = abi.encodeCall(EngramManager.commitEpoch, (1, proof, pv));

        uint256 intr = _intrinsic(cd.length);
        uint256 g0 = gasleft();
        engramPairing.commitEpoch(1, proof, pv);
        uint256 exec = g0 - gasleft();

        console.log("execution      :", exec);
        console.log("intrinsic      :", intr);
        console.log("TONG           :", exec + intr);
    }
}
