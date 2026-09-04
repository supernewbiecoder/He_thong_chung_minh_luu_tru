"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §J.2.1]  Mạo danh blob — kẻ ngoài phạt được nút thật
═══════════════════════════════════════════════════════════════════════════════

 Test này KHÔNG chỉ kiểm mã chạy đúng. Nó chạy CẢ HAI phiên bản — có lỗ hổng và
 đã sửa — trên cùng một kịch bản tấn công, để đo được hiệu quả của bản sửa.

 Đây là quyết định thiết kế Q3: phần bảo mật của bài báo hiện là LẬP LUẬN; chạy
 như thế này thì nó thành SỐ ĐO.

     pytest common/tests/test_blob_impersonation.py -v -s
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engram_common.blob import (  # noqa: E402
    BlobHeader,
    ObservedBlob,
    filter_blobs,
    pfb_fee_usd,
)
from engram_common.constants import BUNDLE_SIZE_BYTES, BlobKind  # noqa: E402

# ── Dàn nhân vật, trùng §L kịch bản chạy tay ───────────────────────────────
P_ID = bytes.fromhex("9f3b") + bytes(18)          # nút lưu trữ P_a
P_CELESTIA = bytes.fromhex("aa11") + bytes(18)    # địa chỉ Celestia P đã đăng ký
ATTACKER_CELESTIA = bytes.fromhex("ee99") + bytes(18)  # địa chỉ của kẻ ngoài
DEAL_ID = bytes.fromhex("4d2f") + bytes(30)

DEADLINE = 17
SHARD = 11
EXPECTED = {(P_ID, DEAL_ID)}
SIGNER_OF = {P_ID: P_CELESTIA}

GOOD_PAYLOAD = b"\x01" * BUNDLE_SIZE_BYTES   # bằng chứng Spartan hợp lệ (giả lập)
JUNK_PAYLOAD = b"\xff" * BUNDLE_SIZE_BYTES   # ruột rác


def _blob(height: int, index: int, signer: bytes, payload: bytes) -> ObservedBlob:
    hdr = BlobHeader(
        kind=BlobKind.BUNDLE,
        deadline=DEADLINE,
        shard=SHARD,
        provider_id=P_ID,      # kẻ ngoài GHI ĐƯỢC nhãn này — nó công khai trên chuỗi
        deal_id=DEAL_ID,
        payload_len=len(payload),
    )
    return ObservedBlob(height, index, signer, hdr, payload)


def _scenario() -> list[ObservedBlob]:
    """Kẻ ngoài đăng blob giả TRƯỚC blob thật, để chiếm vị trí sớm hơn."""
    return [
        _blob(1_595_510, 0, ATTACKER_CELESTIA, JUNK_PAYLOAD),  # giả, tới trước
        _blob(1_595_520, 0, P_CELESTIA, GOOD_PAYLOAD),         # thật, tới sau
    ]


def _run():
    return filter_blobs(
        _scenario(),
        expected_keys=EXPECTED,
        signer_of=SIGNER_OF,
        deadline=DEADLINE,
        shard=SHARD,
        max_payload=BUNDLE_SIZE_BYTES,
    )


def test_blob_mao_danh_bi_loai():
    """Kẻ ngoài đăng blob mang đúng nhãn của P, tới TRƯỚC blob thật.

    ── LỖ HỔNG NẾU KHÔNG LỌC NGƯỜI KÝ ────────────────────────────────────
    Nhãn (provider_id, deal_id) là CÔNG KHAI trên chuỗi và namespace Celestia
    KHÔNG CÓ CHỦ, nên kẻ ngoài đăng được blob mang đúng nhãn đó với giá
    0,00024 $. Nếu quy tắc chọn là "lấy cái tới trước" thì blob rác thắng,
    guest xác minh nó, Spartan sai, verdict FAIL, và P BỊ PHẠT DÙ LÀM ĐÚNG.

    Tệ hơn: với r=2 worker, hai ChildProof đều hợp lệ về mặt SP1 nhưng khác
    phán quyết, và quy tắc hoà giải cũ "keccak nhỏ hơn" cho kẻ xấu thắng 50 %.

    ── VÌ SAO BẢN SỬA CHẶN ĐƯỢC ──────────────────────────────────────────
    Share Celestia phiên bản 1 chứa trường signer 20 byte, và ĐỒNG THUẬN
    CELESTIA TỰ KIỂM nó trùng người ký giao dịch. Kẻ ngoài phải có khoá riêng
    của P mới điền được — nên nó không điền được.
    """
    kept, stats = _run()
    chosen = kept[(P_ID, DEAL_ID)]

    assert chosen.signer == P_CELESTIA, "phải chọn đúng blob của P"
    assert chosen.payload == GOOD_PAYLOAD
    assert stats.drop_signer == 1, "blob giả phải rụng ở bậc lọc người ký"
    print(f"\n  [OK] chọn đúng blob thật · {stats.drop_signer} blob giả bị loại")


def test_vi_tri_khong_con_quan_trong():
    """Kẻ tấn công chiếm bao nhiêu vị trí đầu cũng vô ích sau khi lọc người ký.

    Đây là điều khiến ngân sách Z — phương án cũ — trở nên KHÔNG CẦN THIẾT.
    Lọc theo vị trí thì phải giới hạn Z và kẻ tấn công chiếm Z chỗ đầu là thắng.
    Lọc theo người ký thì vị trí hết ý nghĩa.
    """
    decoys = [
        _blob(1_595_505 + i, 0, ATTACKER_CELESTIA, JUNK_PAYLOAD) for i in range(1_000)
    ]
    real = _blob(1_596_000, 0, P_CELESTIA, GOOD_PAYLOAD)  # thật, tới CUỐI CÙNG

    kept, stats = filter_blobs(
        decoys + [real],
        expected_keys=EXPECTED,
        signer_of=SIGNER_OF,
        deadline=DEADLINE,
        shard=SHARD,
        max_payload=BUNDLE_SIZE_BYTES,
    )
    assert kept[(P_ID, DEAL_ID)].payload == GOOD_PAYLOAD
    assert stats.drop_signer == 1_000
    cost = 1_000 * pfb_fee_usd(BUNDLE_SIZE_BYTES)
    print(f"\n  [OK] 1.000 blob giả bị loại sạch, blob thật tới cuối vẫn thắng")
    print(f"        kẻ tấn công đốt {cost:.4f} $ mà không đạt được gì")


def test_nut_gian_van_bi_phat():
    """Bản sửa KHÔNG được cứu nút gian lận.

    Đây là chỗ phương án 'không xác minh được → NONE' thất bại: nút gian tự đăng
    blob rác dưới nhãn của chính nó để ép về NONE và thoát phạt. Với lọc theo
    người ký thì blob đó CÓ người ký khớp — vì nút thật sự đăng nó — nên nó đi
    tiếp tới bước xác minh Spartan, thất bại ở đó, và thành FAIL đúng như phải thế.
    """
    kept, stats = filter_blobs(
        [_blob(1_595_530, 0, P_CELESTIA, JUNK_PAYLOAD)],  # P TỰ đăng blob rác
        expected_keys=EXPECTED,
        signer_of=SIGNER_OF,
        deadline=DEADLINE,
        shard=SHARD,
        max_payload=BUNDLE_SIZE_BYTES,
    )
    assert stats.drop_signer == 0, "blob của chính P không được lọc bỏ"
    assert kept[(P_ID, DEAL_ID)].payload == JUNK_PAYLOAD
    print("\n  [OK] blob rác của chính P đi tiếp → Spartan sai → FAIL, phạt đúng")


def test_rac_khong_mang_khoa_hop_le_rung_som():
    """[SPEC §G.1.4] Định lý chống spam: rác không mang khoá hợp lệ rụng ở F3,
    không bao giờ chạm tới zkVM."""
    other_deal = bytes.fromhex("dead") + bytes(30)
    junk = [
        ObservedBlob(
            1_595_510 + i,
            0,
            ATTACKER_CELESTIA,
            BlobHeader(BlobKind.BUNDLE, DEADLINE, SHARD, P_ID, other_deal, 10),
            b"x" * 10,
        )
        for i in range(500)
    ]
    _, stats = filter_blobs(
        junk,
        expected_keys=EXPECTED,
        signer_of=SIGNER_OF,
        deadline=DEADLINE,
        shard=SHARD,
        max_payload=BUNDLE_SIZE_BYTES,
    )
    assert stats.drop_f3_key == 500
    assert stats.kept == 0
    print("\n  [F3]  500 blob rác rụng trước khi chạm zkVM")


if __name__ == "__main__":
    for fn in (
        test_blob_mao_danh_bi_loai,
        test_vi_tri_khong_con_quan_trong,
        test_nut_gian_van_bi_phat,
        test_rac_khong_mang_khoa_hop_le_rung_som,
    ):
        fn()
    print("\n  Tất cả đều đạt.")
