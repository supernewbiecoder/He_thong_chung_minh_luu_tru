// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {EngramManager} from "../src/EngramManager.sol";
import {MockVerifier} from "../src/mocks/MockVerifier.sol";
import {MockBlobstream} from "../src/mocks/MockBlobstream.sol";
import {PairingCostVerifier} from "../src/mocks/PairingCostVerifier.sol";
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

    /// snapshot_id PHẢI khớp `snapshotForCurrentEpoch` on-chain (§D.3).
    /// Bản trước điền `keccak256("snapshot")` tuỳ ý và hợp đồng vẫn nhận — đó
    /// chính là lỗ hổng §J.2.6: trường này từng không được kiểm gì cả.
    function _pv(uint64 epoch, address submitter, bytes32 prevRoot, bytes32 vkDigest)
        internal view returns (bytes memory)
    {
        return abi.encodePacked(
            epoch,                            //   0..8
            keccak256("batch"),               //   8..40
            keccak256("da"),                  //  40..72
            uint64(812),                      //  72..80
            keccak256("results"),             //  80..112
            keccak256("resultsData"),         // 112..144
            vkDigest,                         // 144..176
            m.snapshotForCurrentEpoch(),      // 176..208  ← lấy từ hợp đồng
            bytes20(submitter),               // 208..228
            prevRoot,                         // 228..260
            keccak256("newRoot"),             // 260..292
            m.expectedDealCount()             // 292..296  ← phải khớp on-chain
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

    /// ĐÂY LÀ PHÉP ĐO TRUNG TÂM CỦA BÀI BÁO.
    ///
    /// Tuyên bố: chi phí xác minh on-chain KHÔNG ĐỔI theo số hợp đồng trong
    /// mạng. Test này chứng minh bằng cách cam kết ba epoch đại diện cho
    /// 10, 1.000 và 10.000 hợp đồng, rồi so gas.
    ///
    /// Vì sao nó phải đúng: `commitEpoch` nhận ĐÚNG 844 byte calldata bất kể N
    /// — 356 byte Groth16 cộng 296 byte public values cộng mào đầu ABI. Không
    /// có mảng, không có vòng lặp theo N. Toàn bộ N hợp đồng được đại diện bởi
    /// một trường 32 byte duy nhất: results_root.
    ///
    /// Bắt đầu từ epoch 2 để bỏ qua chi phí ghi lần đầu vào currentStateRoot
    /// — epoch 1 luôn đắt hơn vì ô nhớ còn lạnh, và đó là chi phí một lần của
    /// cả hệ chứ không phải chi phí theo N.
    function test_gas_khong_doi_theo_so_hop_dong() public {
        m.commitEpoch(1, new bytes(356), _pvN(1, bytes32(0), 1));

        bytes32 root = m.currentStateRoot();
        uint32[3] memory sizes = [uint32(10), uint32(1000), uint32(10000)];
        uint256[3] memory used;

        for (uint256 i = 0; i < 3; i++) {
            uint64 e = uint64(i + 2);
            bytes memory pv = _pvN(e, root, sizes[i]);
            uint256 g0 = gasleft();
            m.commitEpoch(e, new bytes(356), pv);
            used[i] = g0 - gasleft();
            root = m.currentStateRoot();
        }

        console.log("N=    10 ->", used[0]);
        console.log("N=  1000 ->", used[1]);
        console.log("N= 10000 ->", used[2]);

        assertEq(used[0], used[1], "gas phai khong doi tu N=10 sang N=1000");
        assertEq(used[1], used[2], "gas phai khong doi tu N=1000 sang N=10000");
    }

    /// Như _pv nhưng đặt được num_verified, để test O(1) ở trên đổi N.
    function _pvN(uint64 epoch, bytes32 prevRoot, uint32 n) internal view returns (bytes memory) {
        return abi.encodePacked(
            epoch, keccak256("batch"), keccak256("da"), uint64(812),
            keccak256("results"), keccak256("resultsData"), m.STORAGE_VK_DIGEST(),
            m.snapshotForCurrentEpoch(), bytes20(address(this)), prevRoot,
            keccak256(abi.encodePacked("newRoot", epoch)), n
        );
    }

    /// ĐO GAS ĐẦY ĐỦ, gồm cả phép ghép cặp Groth16 thật.
    ///
    /// `PairingCostVerifier` chạy đúng đường tính toán của một bộ xác minh
    /// Groth16 — hai ecMul, một ecAdd, một ecPairing 4 cặp — bằng các điểm sinh
    /// hợp lệ trên đường cong. Kết quả ghép cặp vô nghĩa, nhưng GAS là thật:
    /// precompile tốn đúng bằng nhau dù trả về 1 hay 0.
    ///
    /// Nhờ vậy đo được con số đầy đủ mà KHÔNG cần sinh bằng chứng SP1 — việc
    /// đòi hàng chục GiB RAM và máy 37 GiB không làm nổi.
    ///
    /// Đây vẫn CHƯA phải bộ xác minh SP1 thật. Nó chỉ khẳng định phần chi phí
    /// mật mã, vốn áp đảo, là bao nhiêu.
    function test_gas_day_du_co_ghep_cap() public {
        EngramManager m2 = new EngramManager(
            new PairingCostVerifier(), blobstream,
            keccak256("ENGRAM_STORAGE_VK_V1"), keccak256("ENGRAM_ACTIVATION_VK_V1"),
            keccak256("ENGRAM_WORKER_PROGRAM_V1"), keccak256("ENGRAM_AGGREGATOR_PROGRAM_V1"),
            bytes32(0)
        );
        bytes memory pv = _pv(1, address(this), bytes32(0), m2.STORAGE_VK_DIGEST());

        uint256 g0 = gasleft();
        m2.commitEpoch(1, new bytes(356), pv);
        uint256 full = g0 - gasleft();

        console.log("commitEpoch CO ghep cap  :", full);
        console.log("spec K.1 truoc day       :", uint256(487109));
        assertGt(full, 400000, "phai vuot 400k khi co ghep cap that");
    }

    /// [SPEC §D.3 / §J.2.6] snapshot_id sai thì hợp đồng TỪ CHỐI.
    ///
    /// Bản trước giải mã trường này rồi bỏ đó. Host bớt một hợp đồng khỏi danh
    /// sách kỳ vọng thì hợp đồng đó không có phán quyết, nút mất doanh thu, và
    /// không ai phát hiện.
    function test_tu_choi_snapshot_sai() public {
        bytes memory pv = abi.encodePacked(
            uint64(1), keccak256("batch"), keccak256("da"), uint64(812),
            keccak256("results"), keccak256("resultsData"), m.STORAGE_VK_DIGEST(),
            keccak256("SO_BIA_DAT"),          // ← snapshot_id sai
            bytes20(address(this)), bytes32(0), keccak256("newRoot"), uint32(13)
        );
        vm.expectRevert(EngramManager.SnapshotMismatch.selector);
        m.commitEpoch(1, new bytes(356), pv);
    }

    /// Sổ thành viên phải ĐỔI khi có hợp đồng mới kích hoạt.
    function test_so_thanh_vien_doi_khi_co_thay_doi() public {
        bytes32 before = m.membershipLog();
        _register(4);
        assertTrue(m.membershipLog() != before, "dang ky nut phai vao so");
    }

    /// [SỬA — nhận xét phản biện] numVerified sai thì hợp đồng TỪ CHỐI.
    ///
    /// Bản trước chỉ lưu numVerified rồi phát sự kiện. Guest báo 1 cho epoch
    /// có 10.000 hợp đồng thì hợp đồng vẫn nhận — "một bằng chứng hợp lệ"
    /// không đồng nghĩa "toàn bộ nghĩa vụ lưu trữ đã hoàn thành".
    function test_tu_choi_khi_chua_xet_het() public {
        bytes memory pv = abi.encodePacked(
            uint64(1), keccak256("batch"), keccak256("da"), uint64(812),
            keccak256("results"), keccak256("resultsData"), m.STORAGE_VK_DIGEST(),
            m.snapshotForCurrentEpoch(), bytes20(address(this)), bytes32(0),
            keccak256("newRoot"),
            uint32(999)                       // ← bịa, không khớp expectedDealCount
        );
        vm.expectRevert(EngramManager.CoverageIncomplete.selector);
        m.commitEpoch(1, new bytes(356), pv);
    }

    /// [SỬA — nhận xét phản biện] Danh sách quyết toán phải chứng minh được là
    /// CÓ TRÊN DA, không chỉ được cam kết.
    ///
    /// Bản trước giải mã results_data_root rồi bỏ đó. Aggregator cam kết một
    /// results_root mà danh sách đầy đủ không ai tải về được → không ai rút
    /// tiền được, và cũng không ai chứng minh được nó sai.
    function test_tu_choi_khi_manifest_khong_co_tren_da() public {
        m.commitEpoch(1, new bytes(356), _pv(1, address(this), bytes32(0), m.STORAGE_VK_DIGEST()));

        IBlobstream.DataRootTuple memory t;
        t.dataRoot = keccak256("DATA_ROOT_KHAC");   // ← không phải resultsDataRoot
        IBlobstream.BinaryMerkleProof memory p;
        vm.expectRevert(EngramManager.ResultsNotAvailable.selector);
        m.finalizeEpoch(1, 812, t, p);
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
        t.dataRoot = keccak256("resultsData");   // khớp results_data_root
        IBlobstream.BinaryMerkleProof memory p;
        vm.expectRevert(EngramManager.BlobstreamRejected.selector);
        m.finalizeEpoch(1, 812, t, p);

        // Chuỗi trạng thái VẪN tiến — đó là toàn bộ điểm của việc tách hai pha.
        assertEq(m.currentStateRoot(), keccak256("newRoot"));
    }
}
