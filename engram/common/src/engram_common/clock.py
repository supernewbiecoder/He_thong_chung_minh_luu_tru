"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §F.1]  Ba đồng hồ  ·  [SPEC §F.2]  Deadline và epoch
═══════════════════════════════════════════════════════════════════════════════

 ── QUY TẮC VÀNG [SPEC §F.1.2] ────────────────────────────────────────────

 KHÔNG một giá trị nào trong ảnh chụp, bundle, hay phán quyết được dẫn xuất từ
 đồng hồ cục bộ. Đồng hồ của hệ là CHIỀU CAO BLOCK CELESTIA.

 Trong toàn bộ mã Engram, `time.time()` chỉ được dùng cho ghi log và hẹn giờ
 poll — không bao giờ cho logic giao thức. Mô-đun này KHÔNG import `time`.

 ── VÌ SAO CELESTIA CHỨ KHÔNG PHẢI ETHEREUM ───────────────────────────────

 Có HAI chuỗi và chúng không nhìn thấy nhau: hợp đồng EVM không đọc được chiều
 cao Celestia, Celestia không đọc được Ethereum. Mà ảnh chụp phải cố định
 da_start_height / da_end_height — chiều cao CELESTIA.

 Nếu beacon sinh từ Ethereum thì hệ phải trả lời "deadline mở lúc block Eth h,
 vậy nó là block Celestia nào?" — không ai trả lời được nếu không thêm một
 ORACLE CHIỀU CAO, tức thêm một bên phải tin và một chỗ để tấn công.

 Chuyển beacon sang Celestia thì câu hỏi đó BIẾN MẤT, không phải được trả lời
 hay hơn.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .constants import PUBLIC_VALUES_BYTES, TimingProfile

# ═══════════════════════════════════════════════════════════════════════════
# 1. ĐỒNG HỒ
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Slot:
    """Một ô thời gian: deadline thứ `deadline_idx` của epoch thứ `epoch`."""

    epoch: int
    deadline_idx: int
    open_height: int  # h_d — beacon sinh tại đây
    window_start: int  # h_d + δ
    window_end: int  # h_d + δ + W  (nửa mở)

    @property
    def absolute_deadline(self) -> int:
        """Chỉ số deadline tuyệt đối, dùng trong tiêu đề blob."""
        return self.epoch * 1_000_000 + self.deadline_idx


class Clock:
    """Quy đổi chiều cao block Celestia ↔ (epoch, deadline).

    `genesis_height` là chiều cao mà giao thức bắt đầu tính. Mọi thứ khác suy ra
    bằng số học — KHÔNG cần giao dịch `openEpoch`, nên bớt một giao dịch, bớt
    một phụ thuộc tính sống, bớt một chỗ để tấn công. [SPEC §F.2.1 ④]
    """

    def __init__(self, profile: TimingProfile, genesis_height: int):
        self.p = profile
        self.h0 = genesis_height

    def slot_of(self, height: int) -> Slot:
        """Chiều cao nào rơi vào deadline nào."""
        if height < self.h0:
            raise ValueError(f"chiều cao {height} nằm trước genesis {self.h0}")
        n = (height - self.h0) // self.p.deadline_len_blocks
        epoch, d = divmod(n, self.p.deadlines_per_epoch)
        return self.slot_at(epoch, d)

    def slot_at(self, epoch: int, deadline_idx: int) -> Slot:
        """[SPEC §F.2.1] h_d = H₀ + (D·e + d) · L_d"""
        n = epoch * self.p.deadlines_per_epoch + deadline_idx
        h = self.h0 + n * self.p.deadline_len_blocks
        ws = h + self.p.beacon_delay_blocks
        return Slot(epoch, deadline_idx, h, ws, ws + self.p.submit_window_blocks)

    def beacon_heights(self, slot: Slot) -> list[int]:
        """[SPEC §F.2.1] k_mix block liên tiếp, tính lùi từ h_d."""
        return [slot.open_height - i for i in range(self.p.beacon_mix_blocks)]

    def in_submit_window(self, slot: Slot, height: int) -> bool:
        return slot.window_start <= height < slot.window_end

    def epoch_bounds(self, epoch: int) -> tuple[int, int]:
        """Cửa sổ DA của cả epoch. [SPEC §F.2.1 ③] Lát kín: da_start(e+1) ==
        da_end(e). Không kẽ hở, không chồng lấn, không phát lại — hợp đồng chỉ
        kiểm một bất đẳng thức và một phép bằng."""
        first = self.slot_at(epoch, 0)
        last = self.slot_at(epoch, self.p.deadlines_per_epoch - 1)
        return first.open_height, last.window_end


# ═══════════════════════════════════════════════════════════════════════════
# 2. PUBLIC VALUES — 296 BYTE  ·  [SPEC §D.2.1]
# ═══════════════════════════════════════════════════════════════════════════
#
# PHẢI khớp bit-để-bit với `_decodePublicValues` trong EngramManager.sol.
# Đây là bề mặt đóng băng: bên trong guest có thể là 10.000 bằng chứng Spartan;
# ra tới hợp đồng chỉ còn 296 byte cố định. Đó là lý do gas là O(1).
#
# LƯU Ý VỀ THỨ TỰ BYTE: Solidity đọc bằng bytes8/bytes32 nên là BIG-ENDIAN.
# Python phải đóng gói big-endian cho khớp. Đây là loại lỗi im lặng nhất trong
# cả hệ — bằng chứng hợp lệ bị từ chối mà không có thông điệp gì.

_PV = struct.Struct(
    ">"     # BIG-endian, khớp Solidity
    "Q"     #   0..8    epoch
    "32s"   #   8..40   batch_root        ← guest TỰ TÍNH
    "32s"   #  40..72   da_commitment     = DataRootTupleRoot
    "Q"     #  72..80   da_nonce
    "32s"   #  80..112  results_root      ← guest TỰ TÍNH từ biến verdict
    "32s"   # 112..144  results_data_root
    "32s"   # 144..176  storage_vk_digest ← guest TỰ TÍNH, hợp đồng so hằng ghim
    "32s"   # 176..208  snapshot_id
    "20s"   # 208..228  submitter         ← chống front-run
    "32s"   # 228..260  prev_state_root
    "32s"   # 260..292  new_state_root    ← guest TỰ TÍNH
    "I"     # 292..296  num_verified      ← guest TỰ ĐẾM
)


@dataclass(frozen=True)
class PublicValues:
    """Toàn bộ những gì zkVM nói ra cho thế giới bên ngoài. 296 byte, không hơn.

    ── BA LOẠI TRƯỜNG, VÀ VÌ SAO PHẢI PHÂN BIỆT [SPEC §D.2.2] ───────────────

    GUEST TỰ TÍNH   batch_root · results_root · storage_vk_digest ·
                    new_state_root · num_verified
                    → KHÔNG AI nói dối được. Chúng là đầu ra của phép tính
                      trong mạch, nên đổi được chúng nghĩa là phá SP1.

    HOST TRÌNH      da_commitment · da_nonce · results_data_root · submitter
                    → Host trình bừa được, nhưng hợp đồng bác. Đây là các
                      trường TRỎ RA NGOÀI, mạch không tự biết.

    HẰNG SỐ GHIM    STORAGE_VK_DIGEST · ACTIVATION_VK_DIGEST · các vkey
                    → KHÔNG nằm ở đây. Chúng là `immutable` trong Solidity.
                      Guest xuất giá trị tính được, hợp đồng so với hằng số.

    Bỏ bước so hằng số thì host tự sinh một khoá xác minh yếu, guest tính đúng
    digest của khoá yếu đó, và mọi thứ khớp — bằng chứng "hợp lệ" cho một hệ
    chứng minh mà host giữ cửa sau.
    """

    epoch: int
    batch_root: bytes
    da_commitment: bytes
    da_nonce: int
    results_root: bytes
    results_data_root: bytes
    storage_vk_digest: bytes
    snapshot_id: bytes
    submitter: bytes  # 20 B
    prev_state_root: bytes
    new_state_root: bytes
    num_verified: int

    def pack(self) -> bytes:
        raw = _PV.pack(
            self.epoch,
            self.batch_root,
            self.da_commitment,
            self.da_nonce,
            self.results_root,
            self.results_data_root,
            self.storage_vk_digest,
            self.snapshot_id,
            self.submitter,
            self.prev_state_root,
            self.new_state_root,
            self.num_verified,
        )
        assert len(raw) == PUBLIC_VALUES_BYTES, f"public values phải là 296 B, được {len(raw)}"
        return raw

    @classmethod
    def unpack(cls, raw: bytes) -> "PublicValues":
        if len(raw) != PUBLIC_VALUES_BYTES:
            raise ValueError(f"public values phải là 296 B, nhận {len(raw)}")
        return cls(*_PV.unpack(raw))


assert _PV.size == PUBLIC_VALUES_BYTES, (
    f"bố cục public values sai: {_PV.size} != {PUBLIC_VALUES_BYTES}. "
    "Sửa ở đây thì PHẢI sửa cả _decodePublicValues trong EngramManager.sol."
)

# Bố cục offset, để test đối chiếu hai phía Python ↔ Solidity.
PV_OFFSETS: dict[str, tuple[int, int]] = {
    "epoch": (0, 8),
    "batch_root": (8, 32),
    "da_commitment": (40, 32),
    "da_nonce": (72, 8),
    "results_root": (80, 32),
    "results_data_root": (112, 32),
    "storage_vk_digest": (144, 32),
    "snapshot_id": (176, 32),
    "submitter": (208, 20),
    "prev_state_root": (228, 32),
    "new_state_root": (260, 32),
    "num_verified": (292, 4),
}
