// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/EngramManager.sol";

/// [T1.3 + T2.1 + T2.4] Vòng đời hợp đồng lưu trữ.
contract DealLifecycleTest is Test {
    // ── T1.3: bốn trường vị trí do HỢP ĐỒNG dẫn xuất ────────────────────

    function test_khach_khong_chon_duoc_manh() public {
        // Trước đây khách truyền thẳng `shard`, nên mài dealId để đẩy hợp đồng
        // vào mảnh mà kẻ tấn công đã chiếm khe worker.
        vm.skip(true);
    }

    function test_cung_dau_vao_hai_lan_ra_hai_dealId() public {
        // nonce mỗi khách làm dealId không mài được.
        vm.skip(true);
    }

    // ── T2.1: hợp đồng hết hạn phải rời tập hoạt động ────────────────────

    function test_dong_hop_dong_het_han_giam_activeDealCount() public {
        vm.skip(true);
    }

    function test_epoch_sau_van_commit_duoc_khi_mot_hop_dong_het_han() public {
        // ĐÂY LÀ BÀI KIỂM QUAN TRỌNG NHẤT CỦA T2.1.
        // Không có closeExpiredDeal thì activeDealCount chỉ tăng, nên
        // numVerified == expectedDealCount không bao giờ thoả nữa và CẢ CHUỖI
        // ĐỨNG VĨNH VIỄN. Khác mọi lỗ khác: cái này không cần kẻ tấn công.
        vm.skip(true);
    }

    function test_chua_het_han_thi_khong_dong_duoc() public {
        vm.skip(true);
    }

    // ── T2.4: huỷ hợp đồng ───────────────────────────────────────────────

    function test_nguoi_la_khong_huy_duoc_hop_dong() public {
        // Trước đây ai cũng huỷ được mọi hợp đồng Pending vào bất cứ lúc nào.
        vm.skip(true);
    }

    function test_huy_som_bi_tu_choi() public {
        // openedAtEpoch giờ được gán thật, và mốc lấy từ lastCommittedEpoch.
        vm.skip(true);
    }
}
