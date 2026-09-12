"""[SỬA D1 + D2] Lá quyết toán phải buộc chặt số tiền vào digest.

Hai lỗ được vá ở đây, và chúng nằm trên cùng một đường tấn công:

D1. `claimSettlement` bản trước nhận `leafDigest` đã băm sẵn cùng `beneficiary`,
    `rewardWei`, `slashWei` làm tham số RỜI, rồi chỉ kiểm digest có trong cây.
    Danh sách quyết toán công bố trên DA nên ai cũng dựng được một cặp hợp lệ,
    rồi điền số tiền tuỳ ý. Bản vá: hợp đồng tự băm lại từ các trường.

D2. Cây Merkle không tách miền lá với nút trong, nên một nút trong trình ra
    được như thể nó là lá, kèm đường ngắn hơn. Bản vá: nút trong mang tiền tố
    0x01, lá mang nhãn ENGRAM_LEAF_V1.
"""

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "aggregator" / "src"))

from engram_common.crypto import keccak, merkle_root, merkle_proof, merkle_verify, NODE_TAG
from engram_common.verdict import Verdict
from aggregator.aggregate import SettlementLeaf

PID = bytes(range(20))
DID = bytes(32)


def _leaf(**kw):
    base = dict(epoch=7, provider_id=PID, deal_id=DID, verdict=Verdict.PASS,
                challenges_total=16, challenges_passed=16,
                reward_wei=10**12, slash_wei=0)
    base.update(kw)
    return SettlementLeaf(**base)


def test_doi_so_tien_thi_doi_digest():
    """Đây là bất biến mà D1 thiếu: số tiền phải nằm TRONG ảnh trước."""
    assert _leaf().digest() != _leaf(reward_wei=10**18).digest()


def test_doi_nguoi_nhan_thi_doi_digest():
    assert _leaf().digest() != _leaf(provider_id=bytes(20)).digest()


def test_doi_epoch_thi_doi_digest():
    """Không có epoch trong digest thì hai epoch có lá giống hệt sẽ đụng
    `settlementClaimed`, và lá thứ hai vĩnh viễn không rút được."""
    assert _leaf(epoch=7).digest() != _leaf(epoch=8).digest()


def test_bo_cuc_digest_khop_abi_encodePacked():
    """Khớp bit-để-bit với `_leafDigest` trong EngramManager.sol.

    `abi.encodePacked` là big-endian, nên ảnh trước phải là:
      "ENGRAM_LEAF_V1" | epoch(8) | provider(20) | dealId(32)
      | verdict(1) | ct(4) | cp(4) | reward(32) | slash(32)
    """
    lf = _leaf()
    expect = keccak(
        b"ENGRAM_LEAF_V1",
        (7).to_bytes(8, "big"),
        PID,
        DID,
        bytes([int(Verdict.PASS)]),
        (16).to_bytes(4, "big"),
        (16).to_bytes(4, "big"),
        (10**12).to_bytes(32, "big"),
        (0).to_bytes(32, "big"),
    )
    assert lf.digest() == expect
    assert len(b"ENGRAM_LEAF_V1") + 8 + 20 + 32 + 1 + 4 + 4 + 32 + 32 == 147


def test_nut_trong_khong_trinh_ra_duoc_nhu_la():
    """D2. Trước khi vá, nút trong `keccak(l0,l1)` là một giá trị 32 byte y hệt
    một lá, nên trình nó kèm đường ngắn hơn vẫn khớp gốc."""
    leaves = [keccak(b"la", bytes([i])) for i in range(4)]
    root = merkle_root(leaves)
    nut_trong_cu = keccak(leaves[0], leaves[1])       # cách băm CŨ
    assert not merkle_verify(nut_trong_cu, [keccak(leaves[2], leaves[3])], 0, root)


def test_duong_merkle_that_van_kiem_duoc():
    leaves = [_leaf(epoch=e).digest() for e in range(5)]
    root = merkle_root(leaves)
    for i in range(5):
        assert merkle_verify(leaves[i], merkle_proof(leaves, i), i, root)


def test_nut_trong_co_tien_to():
    leaves = [keccak(b"a"), keccak(b"b")]
    assert merkle_root(leaves) == keccak(NODE_TAG, leaves[0], leaves[1])
