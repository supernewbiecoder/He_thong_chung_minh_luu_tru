// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {EngramManager} from "../src/EngramManager.sol";
import {MockVerifier} from "../src/mocks/MockVerifier.sol";
import {MockBlobstream} from "../src/mocks/MockBlobstream.sol";
// Phải import ĐÚNG interface để lấy kiểu struct.
//
// Bản trước khai báo một interface `IBlobstreamTypes` riêng ở cuối tệp với
// struct y hệt. Solidity coi hai struct cùng hình dạng nhưng khác nơi khai báo
// là HAI KIỂU KHÁC NHAU, không tự chuyển đổi được. Kết quả:
//   "Invalid implicit conversion from IBlobstreamTypes.DataRootTuple
//    to IBlobstream.DataRootTuple"
import {IBlobstream} from "../src/interfaces/IBlobstream.sol";

/// Test hợp đồng. Mục tiêu KHÔNG phải phủ mã tối đa, mà là kiểm ba tính chất
/// mà bài báo tuyên bố, cộng ba lỗ hổng đã vá.
contract EngramManagerTest is Test {
    EngramManager m;
    MockVerifier verifier;
    MockBlobstream blobstream;

    address customer = address(0xC1);
    address provider = address(0x9F);
    bytes32 constant DEAL = bytes32(uint256(0x4d2f));

    function setUp() public {
        verifier = new MockVerifier();
        blobstream = new MockBlobstream();
        m = new EngramManager(
            verifier, blobstream,
            keccak256("ENGRAM_STORAGE_VK_V1"),
            keccak256("ENGRAM_ACTIVATION_VK_V1"),
            keccak256("ENGRAM_WORKER_PROGRAM_V1"),
            keccak256("ENGRAM_AGGREGATOR_PROGRAM_V1"),
            bytes32(0)
        );
        vm.deal(customer, 100 ether);
        vm.deal(provider, 100 ether);
    }

    function _register(uint64 slots) internal {
        // Tính TIỀN TRƯỚC, prank SAU.
        //
        // ── BẪY FOUNDRY, và nó hỏng im lặng ────────────────────────────────
        //
        // `vm.prank` chỉ đổi msg.sender cho ĐÚNG MỘT lời gọi kế tiếp. Viết
        //
        //     vm.prank(provider);
        //     m.registerProvider{value: slots * m.MIN_COLLATERAL_PER_SLOT()}(…);
        //
        // thì `m.MIN_COLLATERAL_PER_SLOT()` là một lời gọi, và NÓ ăn mất prank.
        // `registerProvider` chạy với msg.sender là hợp đồng test, nên hồ sơ
        // được ghi vào providers[address(this)] thay vì providers[provider].
        //
        // Giao dịch KHÔNG revert. Test chỉ thấy providers[provider] rỗng —
        // "assertion failed: 0 != 4" — và triệu chứng đó không hề gợi ra prank.
        uint256 amount = uint256(slots) * m.MIN_COLLATERAL_PER_SLOT();
        vm.prank(provider);
        m.registerProvider{value: amount}(
            bytes20(uint160(0xAA11)), slots, "/dns4/pa.io/tcp/443", hex"01"
        );
    }

    /*═══════════════════════════════════════════════════════════════════════
      TÍNH CHẤT 1 — cọc phải tỉ lệ số khe  [CHỐT B2-a] [SPEC §J.2.5]

      Không có ràng buộc này, nút đặt 1 ETH rồi nhận bao nhiêu hợp đồng cũng
      được; tới ~10.000 hợp đồng thì cọc mỗi hợp đồng tụt dưới ngưỡng §I.1.3
      và gian lận thành có lãi.
    ═══════════════════════════════════════════════════════════════════════*/

    function test_coc_thieu_thi_tu_choi_dang_ky() public {
        vm.prank(provider);
        vm.expectRevert(EngramManager.InsufficientCollateral.selector);
        m.registerProvider{value: 1}(bytes20(uint160(0xAA11)), 1024, "/dns4/pa.io", hex"01");
    }

    function test_coc_du_thi_dang_ky_duoc() public {
        _register(4);
        // StorageProvider có ĐÚNG 8 trường, và getter tự sinh trả về cả 8 —
        // kể cả `multiaddr` kiểu string, vì Solidity chỉ bỏ qua mapping và
        // mảng động, không bỏ qua string.
        //
        //   1 celestiaAddress   5 withdrawRequestedAtEpoch
        //   2 collateralWei     6 registeredAtEpoch
        //   3 capacitySlots     7 providerRoot
        //   4 usedSlots         8 multiaddr
        (, uint256 col, uint64 cap, , , , , ) = m.providers(provider);
        assertEq(cap, 4);
        assertEq(col, 4 * m.MIN_COLLATERAL_PER_SLOT());
    }

    /*═══════════════════════════════════════════════════════════════════════
      TÍNH CHẤT 2 — phí niêm phong mở khoá khi registerSealed
      [CHỐT B1-a] [SPEC §J.2.4]

      Nút bỏ 1,26 giờ CPU niêm phong TRƯỚC khi kiếm được đồng nào. Không có
      khoản này thì khách mở 1.000 hợp đồng rồi bỏ, nút đốt 1.280 giờ CPU còn
      khách tốn ~1 $ và lấy lại toàn bộ ký quỹ.
    ═══════════════════════════════════════════════════════════════════════*/

    function test_phi_niem_phong_mo_khoa_khi_dang_ky_seal() public {
        _register(4);
        uint256 fee = 0.001 ether;
        uint256 escrow = 10 * 1e12;

        vm.prank(customer);
        m.openDeal{value: escrow + fee}(
            EngramManager.DealParams({
                dealId: DEAL,
                provider: provider,
                pieceRoot: keccak256("piece"),
                pieceSizeReal: 1024,
                pricePerEpochWei: 1e12,
                durationEpochs: 10,
                deadlineIdx: 3,
                shard: 11,
                activationBeacon: keccak256("beacon"),
                sealingFeeWei: fee
            })
        );

        uint256 before = provider.balance;
        vm.prank(provider);
        m.registerSealed(DEAL, keccak256("sealed"), keccak256("proot"));
        assertEq(provider.balance - before, fee, "phi niem phong phai ve nut");
    }

    /*═══════════════════════════════════════════════════════════════════════
      TÍNH CHẤT 3 — commitEpoch là O(1) và có bốn phép kiểm bắt buộc
      [SPEC §D.2 / §I.1.1]
    ═══════════════════════════════════════════════════════════════════════*/

    function _pv(uint64 epoch, address submitter, bytes32 prevRoot, bytes32 vkDigest)
        internal pure returns (bytes memory)
    {
        return abi.encodePacked(
            epoch,                       //   0..8
            keccak256("batch"),          //   8..40
            keccak256("da"),             //  40..72
            uint64(812),                 //  72..80
            keccak256("results"),        //  80..112
            keccak256("resultsData"),    // 112..144
            vkDigest,                    // 144..176
            keccak256("snapshot"),       // 176..208
            bytes20(submitter),          // 208..228
            prevRoot,                    // 228..260
            keccak256("newRoot"),        // 260..292
            uint32(13)                   // 292..296
        );
    }

    function test_public_values_dung_296_byte() public view {
        assertEq(_pv(1, address(this), bytes32(0), m.STORAGE_VK_DIGEST()).length, 296);
    }

    function test_commit_epoch_va_do_gas() public {
        bytes memory pv = _pv(1, address(this), bytes32(0), m.STORAGE_VK_DIGEST());
        bytes memory proof = new bytes(356); // [SPEC §K.1] Groth16 = 356 B

        uint256 g0 = gasleft();
        m.commitEpoch(1, proof, pv);
        uint256 used = g0 - gasleft();

        // CHỈ DÙNG ASCII trong chuỗi Solidity.
        //
        // Solidity từ chối ký tự ngoài ASCII trong chuỗi thường; phải viết
        // unicode"..." mới được. Ký tự "§" ở đây làm cả bản dựng chết với
        // "Error (8936): Invalid character in string".
        //
        // Comment thì thoải mái tiếng Việt — chỉ CHUỖI mới bị ràng buộc.
        console.log("gas commitEpoch:", used);
        console.log("spec K.1 target:", uint256(487109));
        console.log("delta:", used > 487109 ? used - 487109 : 487109 - used);
        assertEq(m.lastCommittedEpoch(), 1);
        assertEq(m.currentStateRoot(), keccak256("newRoot"));
    }

    /// Gas 244.444 này là PHẦN LOGIC HỢP ĐỒNG, chưa gồm xác minh Groth16.
    ///
    /// MockVerifier chỉ kiểm độ dài 356 byte rồi trả về. Bộ xác minh SP1 thật
    /// chạy phép ghép cặp BN254 qua precompile ecPairing, tốn thêm khoảng
    /// 200–250k gas.
    ///
    ///     244.444  logic hợp đồng          ← đo được ở đây
    ///   + ~243.000 xác minh Groth16 thật    ← CHƯA đo
    ///   ─────────
    ///     ~487.000                          ≈ 487.109 trong §K.1
    ///
    /// Con số trong đặc tả khớp tổng, nhưng ĐÓ LÀ SUY LUẬN chứ chưa phải phép
    /// đo. Muốn xác nhận phải deploy bộ xác minh SP1 thật thay MockVerifier.
    function test_gas_phan_ra() public {
        bytes memory pv = _pv(1, address(this), bytes32(0), m.STORAGE_VK_DIGEST());
        uint256 g0 = gasleft();
        m.commitEpoch(1, new bytes(356), pv);
        uint256 logicOnly = g0 - gasleft();

        console.log("logic hop dong (khong Groth16):", logicOnly);
        console.log("spec K.1 (co Groth16 that)    :", uint256(487109));
        console.log("phan con thieu ~= Groth16     :", 487109 - logicOnly);

        // Chốt lại con số đo được để lần sau đổi mã là thấy ngay.
        assertLt(logicOnly, 300000, "logic hop dong phai duoi 300k gas");
    }

    /// [SPEC §D.2.4] Chống front-run. Không có 20 byte submitter thì ai đó theo
    /// dõi mempool, sao chép giao dịch, đẩy phí cao hơn và nộp trước.
    function test_tu_choi_khi_submitter_khong_khop() public {
        bytes memory pv = _pv(1, address(0xBEEF), bytes32(0), m.STORAGE_VK_DIGEST());
        vm.expectRevert(EngramManager.SubmitterMismatch.selector);
        m.commitEpoch(1, new bytes(356), pv);
    }

    /// [SPEC §D.2.2] NEO VÀO HỆ CHỨNG MINH — chỗ cả hệ treo lên.
    /// Không có phép so này, host tự sinh khoá xác minh yếu, guest tính đúng
    /// digest của khoá yếu đó, và mọi thứ khớp.
    function test_tu_choi_khoa_xac_minh_la() public {
        bytes memory pv = _pv(1, address(this), bytes32(0), keccak256("KHOA_GIA"));
        vm.expectRevert(EngramManager.VkDigestMismatch.selector);
        m.commitEpoch(1, new bytes(356), pv);
    }

    /// [SPEC §F.2.6] Epoch PHẢI cam kết đúng thứ tự. Chứng minh chạy song song
    /// được (đường ống L=2) nhưng commitEpoch thì không.
    function test_tu_choi_epoch_sai_thu_tu() public {
        bytes memory pv = _pv(5, address(this), bytes32(0), m.STORAGE_VK_DIGEST());
        vm.expectRevert(EngramManager.EpochOutOfOrder.selector);
        m.commitEpoch(5, new bytes(356), pv);
    }

    /*═══════════════════════════════════════════════════════════════════════
      TÍNH CHẤT 4 — tách commit khỏi finalize  [SPEC §F.2.4]

      Blobstream treo thì epoch kẹt ở Committed và KHÔNG AI MẤT GÌ.
    ═══════════════════════════════════════════════════════════════════════*/

    function test_blobstream_treo_thi_epoch_ket_nhung_khong_mat_tien() public {
        m.commitEpoch(1, new bytes(356), _pv(1, address(this), bytes32(0), m.STORAGE_VK_DIGEST()));
        blobstream.setOutage(true);

        IBlobstream.DataRootTuple memory t;
        IBlobstream.BinaryMerkleProof memory p;
        vm.expectRevert(EngramManager.BlobstreamRejected.selector);
        m.finalizeEpoch(1, 812, t, p);

        // Chuỗi trạng thái VẪN tiến — đó là toàn bộ điểm của việc tách hai pha.
        assertEq(m.currentStateRoot(), keccak256("newRoot"));
    }
}
