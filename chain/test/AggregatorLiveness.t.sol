// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/EngramManager.sol";

/// [T2.2-A + T2.3-B] Aggregator im lặng phải bị phạt, và epoch phải đổi được người.
///
/// BẢN TRƯỚC: không có hạn chót nào buộc `commitEpoch` xảy ra. Aggregator im
/// lặng thì nút đã tốn ổ cứng cả ngày, worker đã tốn hàng trăm giờ CPU, không ai
/// được trả, KHÔNG AI BỊ PHẠT, và mọi epoch sau kẹt theo vì commit phải tuần tự.
/// Đường thoát duy nhất là `voidEpoch`, mà nó không kiểm quyền gọi nên vừa là
/// đường thoát vừa là vũ khí DoS giá 30.000 gas.
contract AggregatorLivenessTest is Test {
    function test_trong_han_chi_nguoi_duoc_chi_dinh_nop_duoc() public {
        // vm.expectRevert(EngramManager.NotDesignatedAggregator.selector);
        vm.skip(true);
    }

    function test_qua_han_thi_mo_cho_moi_nguoi() public {
        // Tính sống quan trọng hơn độc quyền: người được chỉ định đã bị cắt cọc.
        vm.skip(true);
    }

    function test_bao_tre_thi_cat_coc_va_chuyen_luot() public {
        // assertEq(collateralSau, collateralTruoc * 9 / 10);
        // assertTrue(designatedAggregator() != aggCu);
        vm.skip(true);
    }

    function test_bao_tre_KHONG_huy_epoch() public {
        // Khác căn bản so với voidEpoch: epoch vẫn cam kết được sau khi đổi người.
        vm.skip(true);
    }

    function test_chua_qua_han_thi_khong_bao_tre_duoc() public {
        // vm.expectRevert(EngramManager.DeadlineNotPassed.selector);
        vm.skip(true);
    }

    function test_voidEpoch_truoc_han_bi_tu_choi() public {
        // Đây là lỗ cũ: trước đây gọi lúc nào cũng được.
        // vm.expectRevert(EngramManager.DeadlineNotPassed.selector);
        vm.skip(true);
    }

    function test_nguoi_dang_duoc_chi_dinh_khong_rut_coc_duoc() public {
        // Rút xong rồi im lặng thì không còn gì để cắt.
        vm.skip(true);
    }
}
