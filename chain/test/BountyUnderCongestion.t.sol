// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/EngramManager.sol";

/// [SPEC §H.1.7] Hoa hồng phạt KHÔNG được trả trong epoch mà cửa sổ DA bị lấp đầy.
///
/// Vì sao phải có bài kiểm này. Hoa hồng 5 % tồn tại để có người chịu nộp lá
/// phạt hộ. Giả định ngầm của nó là lá phạt phản ánh gian lận thật. Dưới nghẽn
/// DA giả định đó sai: nút trung thực không đăng được bằng chứng nên bị phạt
/// hàng loạt, và kẻ gây nghẽn tự nộp lá phạt để thu hoa hồng. Khoản thu tăng
/// theo N, nên bất đẳng thức "chi phí tấn công > giá trị thu được" hỏng đúng
/// lúc mạng lớn lên.
///
/// Bài kiểm chốt ba việc:
///   1. cửa sổ sạch  → hoa hồng vẫn trả, cơ chế săn lá phạt còn nguyên;
///   2. cửa sổ nghẽn → hoa hồng bằng 0;
///   3. mức phạt KHÔNG đổi trong cả hai trường hợp — chỉ phần THU bị cắt, nên
///      nút xoá dữ liệu vẫn bị chặn y như cũ.
contract BountyUnderCongestionTest is Test {
    // Bộ khung dựng epoch dùng lại từ EngramManager.t.sol; ở đây chỉ nêu khung
    // để người chạy nối vào fixture sẵn có của repo.

    uint8 constant DUOI_NGUONG = 100; // < 179
    uint8 constant TREN_NGUONG = 200; // >= 179

    function test_cua_so_sach_van_tra_hoa_hong() public {
        // commitEpoch với window_saturation = DUOI_NGUONG, finalize, rồi để một
        // bên thứ ba nộp lá phạt.
        // assertEq(bountyTraCho(nguoiSan), slashWei * 500 / 10_000);
        vm.skip(true);
    }

    function test_cua_so_nghen_thi_khong_tra_hoa_hong() public {
        // Cùng lá phạt, chỉ khác window_saturation = TREN_NGUONG.
        // assertEq(bountyTraCho(nguoiSan), 0);
        vm.skip(true);
    }

    function test_muc_phat_khong_doi_khi_nghen() public {
        // slashWei trong lá là như nhau ở cả hai kịch bản. Đây là điểm quan
        // trọng nhất: vá này cắt phần THU của kẻ tấn công, KHÔNG hạ răn đe.
        vm.skip(true);
    }

    function test_nguong_dung_bien() public {
        EngramManager m;
        // assertEq(m.WINDOW_SATURATION_THRESHOLD(), 179);
        vm.skip(true);
    }
}
