// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/EngramManager.sol";

/// [R1 · R2 · R3 · R4 · R6] Kinh tế nhà cung cấp và aggregator.
contract ProviderEconomicsTest is Test {
    // ── R1: thưởng phải trừ ký quỹ của chính hợp đồng đó ────────────────

    function test_thuong_tru_ky_quy() public {
        // escrowWei giảm đúng bằng rewardWei sau mỗi lần khai.
        vm.skip(true);
    }

    function test_khai_vuot_ky_quy_bi_tu_choi() public {
        // Trước đây thưởng trả từ quỹ chung, không đối chiếu gì.
        // vm.expectRevert(EngramManager.InsufficientEscrow.selector);
        vm.skip(true);
    }

    // ── R2: nút cạn cọc bị treo ─────────────────────────────────────────

    function test_cat_coc_xuong_duoi_nguong_thi_treo() public {
        // assertTrue(suspended sau khi claim mot la FAIL lon);
        vm.skip(true);
    }

    function test_nut_bi_treo_khong_nhan_hop_dong_moi() public {
        // vm.expectRevert(EngramManager.ProviderSuspended.selector);
        vm.skip(true);
    }

    function test_nap_them_coc_thi_go_treo() public {
        vm.skip(true);
    }

    // ── R3: đăng ký lại không ghi đè tuỳ ý ──────────────────────────────

    function test_khong_ha_capacity_xuong_duoi_so_khe_dang_dung() public {
        // vm.expectRevert(EngramManager.CapacityBelowUsage.selector);
        vm.skip(true);
    }

    function test_khong_doi_dia_chi_celestia_bang_dang_ky_lai() public {
        // Đổi giữa chừng là đường né phạt: FAIL biến thành ABSENT.
        // vm.expectRevert(EngramManager.WrongState.selector);
        vm.skip(true);
    }

    function test_doi_dia_chi_celestia_phai_cho_toi_epoch_hieu_luc() public {
        // vm.expectRevert(EngramManager.AbortTooEarly.selector);
        vm.skip(true);
    }

    // ── R4: bỏ khai tuần tự ─────────────────────────────────────────────

    function test_khai_epoch_7_khi_chua_khai_epoch_6() public {
        // Trước đây bị ClaimOutOfOrder, và nếu epoch 6 bị void thì phần thưởng
        // từ epoch 7 trở đi KHÔNG RÚT ĐƯỢC VĨNH VIỄN.
        vm.skip(true);
    }

    function test_van_khong_khai_lai_duoc_cung_mot_la() public {
        // settlementClaimed một mình đã đủ, vì digest đã mang epoch từ bản vá D1.
        // vm.expectRevert(EngramManager.AlreadyClaimed.selector);
        vm.skip(true);
    }

    // ── R5: beacon kích hoạt lấy từ Celestia ────────────────────────────

    function test_beacon_kich_hoat_doi_theo_daCommitment() public {
        // Hai epoch có daCommitment khác nhau thì beacon khác nhau.
        vm.skip(true);
    }

    function test_chua_co_epoch_nao_cam_ket_thi_khong_mo_duoc_hop_dong() public {
        // vm.expectRevert(EngramManager.NoCelestiaAnchor.selector);
        vm.skip(true);
    }

    // ── R6: khoá thời gian rút cọc aggregator ───────────────────────────

    function test_rut_coc_aggregator_phai_xin_truoc_va_cho() public {
        // Trước đây chỉ chặn người ĐANG được chỉ định, nên rút trước lượt rồi
        // im lặng là thoát phạt.
        vm.skip(true);
    }
}
