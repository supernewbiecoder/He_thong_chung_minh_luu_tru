"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §D.3]  Sổ thành viên và snapshot_id
═══════════════════════════════════════════════════════════════════════════════

 Sổ thành viên trả lời câu hỏi mà mọi phán quyết đều dựa vào:
 "hợp đồng nào PHẢI có bằng chứng ở deadline này?"

 Không có nó thì ABSENT vô nghĩa — không biết ai lẽ ra phải nộp thì không biết
 ai vắng mặt.

 ── LỖ HỔNG NÓ ĐÓNG  [SPEC §J.2.6] ────────────────────────────────────────

 Bản trước để guest lặp trên `expected` mà không nói danh sách đó ở đâu ra, và
 hợp đồng giải mã `snapshot_id` rồi BỎ ĐÓ. Host bớt một hợp đồng thì hợp đồng
 đó không có phán quyết, nút mất doanh thu, KHÔNG AI PHÁT HIỆN.

 Không phải phạt oan — là chặn thu nhập, và im lặng hơn nhiều.

 ── KIẾN TRÚC ─────────────────────────────────────────────────────────────

   on-chain   một giá trị tích luỹ 32 byte, một keccak mỗi thao tác  — O(1)
   trên DA    toàn văn, namespace kind=04                            — O(N)

 Việc O(N) nằm ở nơi nó rẻ; việc O(1) nằm ở nơi nó đắt.

 ── ĐIỀU NÓ THẬT SỰ MUA ĐƯỢC ──────────────────────────────────────────────

 Không phải "phát hiện được gian lận" mà là DỜI CHI PHÍ SAI TỪ NẠN NHÂN SANG
 HOST. Host bỏ sót thì bằng chứng bị hợp đồng từ chối, và nó đốt hàng giờ SP1
 không thu được gì.

 ── ĐIỂM DỄ PHÁT BIỂU SAI ─────────────────────────────────────────────────

 Không phải "host phải lưu để bảo vệ quyền lợi của host". Nguồn sự thật là
 CHUỖI; host chỉ cần DỰNG LẠI ĐƯỢC, và KHÔNG CẦN ĐƯỢC TIN.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .crypto import keccak


class MembershipKind(bytes, Enum):
    """Phải khớp BYTE-ĐỂ-BYTE với hằng số trong EngramManager.sol.

    Solidity `bytes32 constant M_PROVIDER = "PROVIDER"` đệm PHẢI bằng số 0 —
    chuỗi nằm ở đầu, không phải cuối. Đệm sai đầu là giá trị khác, và phát lại
    ra kết quả khác mà không có thông điệp lỗi nào.
    """

    PROVIDER = b"PROVIDER"
    DEAL_OPEN = b"DEAL_OPEN"
    DEAL_ACTIVE = b"DEAL_ACTIVE"
    DEAL_CLOSED = b"DEAL_CLOSED"

    def as_bytes32(self) -> bytes:
        return self.value.ljust(32, b"\0")


@dataclass(frozen=True)
class MembershipEntry:
    """Một thay đổi thành viên, tương ứng một lời gọi `_logMembership` on-chain."""

    kind: MembershipKind
    a: bytes  # 32 B
    b: bytes  # 32 B


def replay(entries: list[MembershipEntry], genesis: bytes = bytes(32)) -> bytes:
    """Phát lại sổ, ra đúng giá trị `membershipLog` mà hợp đồng đang giữ.

    Phải khớp Solidity:
        membershipLog = keccak256(abi.encodePacked(membershipLog, kind, a, b))

    `abi.encodePacked` nối thẳng không đệm, nên ba giá trị 32 byte thành 96 byte.

    BỚT MỘT MỤC LÀ RA GIÁ TRỊ KHÁC. Đó là toàn bộ cơ chế.
    """
    log = genesis
    for e in entries:
        log = keccak(log, e.kind.as_bytes32(), e.a.rjust(32, b"\0"), e.b.rjust(32, b"\0"))
    return log


@dataclass
class DealRecord:
    """Một hợp đồng trong sổ, ở dạng guest cần."""

    provider_id: bytes
    deal_id: bytes
    sealed_root: bytes
    deadline_idx: int
    shard: int
    declared_unavailable: bool = False


@dataclass
class MembershipRegistry:
    """Toàn văn sổ, công bố lên DA namespace kind=04.

    [SPEC §D.3.3] Vì sao lên DA chứ không bắt worker đọc EVM: worker ĐÃ ĐỌC DA
    rồi, nên không thêm phụ thuộc hạ tầng nào. Bắt nó chạy thêm node EVM đầy đủ
    hoặc indexer là thêm một chỗ để hỏng và một chỗ để tấn công.
    """

    epoch: int
    cut_height: int  # chiều cao Celestia lúc cắt sổ
    entries: list[MembershipEntry] = field(default_factory=list)
    deals: list[DealRecord] = field(default_factory=list)

    def snapshot_id(self, genesis: bytes = bytes(32)) -> bytes:
        return replay(self.entries, genesis)

    def expected_for(self, deadline_idx: int, shard: int) -> list[DealRecord]:
        """Danh sách kỳ vọng cho một ô (deadline, mảnh).

        Guest gọi hàm này SAU khi đã đối chiếu `snapshot_id`. Trước khi đối
        chiếu thì sổ chưa đáng tin và không được dùng.
        """
        out = [d for d in self.deals if d.deadline_idx == deadline_idx and d.shard == shard]
        out.sort(key=lambda d: (d.provider_id, d.deal_id))
        return out


class SnapshotMismatch(RuntimeError):
    """Sổ tải từ DA không khớp giá trị on-chain.

    Guest PHẢI dừng ở đây. Đi tiếp với sổ sai nghĩa là phán quyết dựa trên một
    danh sách hợp đồng mà không ai xác nhận — đúng lỗ hổng §J.2.6.
    """


def verify_registry(registry: MembershipRegistry, onchain_snapshot_id: bytes, epoch: int) -> None:
    """Cửa vào bắt buộc trước khi dùng sổ."""
    if registry.epoch != epoch:
        raise SnapshotMismatch(f"sổ của epoch {registry.epoch}, đang xử lý epoch {epoch}")
    got = registry.snapshot_id()
    if got != onchain_snapshot_id:
        raise SnapshotMismatch(
            f"phát lại sổ ra {got.hex()[:16]}…, on-chain giữ "
            f"{onchain_snapshot_id.hex()[:16]}… — sổ đã bị sửa hoặc bớt mục"
        )
