"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §A.4.3]  WorkerLottery
 [CHỐT F1-c]    Trần thích ứng
 [CHỐT F2]      Xoay vòng theo thời gian chứng minh
 [CHỐT F3]      Lọc worker không phản hồi
═══════════════════════════════════════════════════════════════════════════════

 ── BA BỘ LỌC, GIẢI BA BÀI TOÁN KHÁC NHAU ─────────────────────────────────

   ① SỐNG        loại worker đang bị đình chỉ vì bỏ việc nhiều lần
   ② XOAY VÒNG   loại worker còn đang bận chứng minh việc trước
   ③ TRẦN        loại worker đã giữ quá phần của mình trong epoch này

 Thứ tự là bắt buộc. ① trước vì worker chết thì mọi thứ khác vô nghĩa. ② trước
 ③ vì bận là ràng buộc VẬT LÝ, còn trần là ràng buộc CHÍNH SÁCH — không bao giờ
 nên hy sinh cái vật lý để giữ cái chính sách.

 ── VÌ SAO XỔ SỐ THEO BEACON, KHÔNG GÁN CỐ ĐỊNH ──────────────────────────

 Ba phép gán trong hệ, ba quy tắc khác nhau, và lẫn lộn chúng là lỗ hổng:

   hợp đồng → deadline   cố định cả đời      để nút lên lịch tài nguyên
   hợp đồng → mảnh       cố định cả đời      để namespace ổn định
   mảnh → worker         XOAY mỗi deadline   để kẻ xấu KHÔNG tự chọn được
                                             phục vụ mảnh nó nhắm

 Nếu gán worker cũng cố định, kẻ xấu chỉ cần đăng ký làm worker đúng mảnh của
 đối thủ rồi im lặng mọi deadline — chi phí một lần đăng ký.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engram_common.constants import WORKER_REDUNDANCY_R, WORKER_SLOT_CAP_RATIO
from engram_common.crypto import keccak

# ═══════════════════════════════════════════════════════════════════════════
# 1. TRẠNG THÁI WORKER
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_MISS_THRESHOLD = 3
"""[CHỐT F3] Bỏ bao nhiêu việc liên tiếp thì bị đình chỉ.

Không đặt 1 vì một lần lỡ có thể do mạng chứ không do gian. Không đặt quá cao
vì mỗi lần bỏ là một ô không được phủ và các hợp đồng trong ô mất doanh thu."""

DEFAULT_SUSPENSION_DEADLINES = 8
"""[CHỐT F3] Đình chỉ bao lâu, tính bằng deadline.

PHẢI HỮU HẠN. Cấm vĩnh viễn thì worker gặp sự cố mạng một lần là mất cả khoản
cọc đã bỏ ra, và không ai dám làm worker. Hết hạn thì bộ đếm reset về 0 và
worker vào lại bể — có đường quay lại, nhưng không miễn phí."""


@dataclass
class WorkerEntry:
    """Một worker trong bể xổ số.

    Ba trường trạng thái dưới đây KHÔNG cần giao dịch on-chain riêng để cập
    nhật. Chúng suy ra được từ thứ đã có: chứng cứ phủ đầy đủ ở tầng aggregator
    (§J.2.2) cho biết ô nào có ChildProof, ô nào không. Nên tính sống là SẢN
    PHẨM PHỤ của một cơ chế đã tồn tại, không phải một cơ chế mới.

    Nếu làm bằng nhịp tim on-chain thì mỗi worker mỗi chu kỳ một giao dịch —
    tức quay lại đúng đường cơ sở O(N) mà kiến trúc này bác bỏ (§I.1.1).
    """

    worker_id: bytes
    stake_wei: int
    last_assigned_deadline: int = -(10**9)
    consecutive_misses: int = 0
    suspended_until_deadline: int = -1

    def is_live(self, deadline: int) -> bool:
        return deadline >= self.suspended_until_deadline

    def is_free(self, deadline: int, cooldown: int) -> bool:
        """Còn bận chứng minh việc trước không."""
        return deadline >= self.last_assigned_deadline + cooldown + 1


@dataclass
class LotteryStats:
    """Vì sao ai bị loại — để chẩn đoán được khi mạng cư xử lạ."""

    pool: int = 0
    dropped_suspended: int = 0
    dropped_cooldown: int = 0
    dropped_cap: int = 0
    relaxed_cap: bool = False
    relaxed_cooldown: bool = False
    chosen: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# 2. THAM SỐ SUY RA, KHÔNG PHẢI HẰNG SỐ
# ═══════════════════════════════════════════════════════════════════════════


def cooldown_deadlines(t_worker_seconds: float, deadline_len_seconds: float) -> int:
    """[CHỐT F2] Worker phải nghỉ bao nhiêu deadline sau khi nhận một ô.

    Sinh bằng chứng SP1 tốn HÀNG GIỜ, còn deadline chỉ cách nhau 30 phút. Nếu
    một worker nhận việc ở deadline liên tiếp, nó tích việc chưa xong và hàng
    đợi dài ra vô hạn — đường ống chữa được ĐỘ TRỄ, không chữa được THÔNG LƯỢNG
    (§F.2.6).

    Nghỉ `cooldown` deadline bảo đảm không worker nào có hai việc chồng nhau.
    """
    if deadline_len_seconds <= 0:
        return 0
    return max(0, math.ceil(t_worker_seconds / deadline_len_seconds) - 1)


def adaptive_cap_ratio(
    n_workers: int, r: int = WORKER_REDUNDANCY_R, floor_ratio: float = WORKER_SLOT_CAP_RATIO
) -> float:
    """[CHỐT F1-c] Trần thích ứng: `max(0,05, r / n_workers)`.

    ── VẤN ĐỀ CỦA TRẦN CỐ ĐỊNH ─────────────────────────────────────────────

    Trần 5 % cố định chỉ RÀNG BUỘC ĐƯỢC khi có ít nhất r/0,05 = 40 worker. Dưới
    mức đó, tổng khe khả dụng (n × 5 %) nhỏ hơn tổng khe cần gán (số ô × r), nên
    quy tắc thoát kích hoạt gần như mọi lần và trần thành trang trí.

    Đo được ở mạng 5 worker: kẻ nắm 88 % cọc chiếm 46,5 % số ô, dù cấu hình ghi
    trần 5 %. Người đọc cấu hình sẽ tưởng mạng được bảo vệ. Nó không.

    ── TRẦN THÍCH ỨNG ──────────────────────────────────────────────────────

    Luôn khả thi ở mọi quy mô, nên quy tắc thoát gần như không bao giờ cần dùng,
    và trần luôn chặt nhất có thể. Ở mạng nhỏ nó nới ra vì buộc phải thế — nhưng
    con số nới ra là TƯỜNG MINH, thay vì một trần 5 % im lặng không hoạt động.
    """
    if n_workers <= 0:
        return 1.0
    return max(floor_ratio, r / n_workers)


def required_workers(n_shards: int, r: int = WORKER_REDUNDANCY_R, cooldown: int = 0) -> int:
    """[CHỐT F2] Số worker tối thiểu để xoay vòng KHÔNG bị nghẽn.

    Mỗi deadline cần `n_shards × r` worker rảnh. Với nghỉ `cooldown` deadline,
    mỗi worker chỉ rảnh 1 trong (cooldown+1) deadline. Nên:

        n_workers ≥ n_shards · r · (cooldown + 1)

    ── ĐÂY LÀ RÀNG BUỘC CHẶT HƠN TRẦN KHE RẤT NHIỀU ────────────────────────

    Trần khe cần 40 worker. Xoay vòng thì tuỳ t_worker, và t_worker ĐO ĐƯỢC
    GIÁN TIẾP: ở N=10.000 một ô tốn ~192e9 chu kỳ, nên với worker chạy ~17
    Mcycle/s thì t_worker ≈ 3,1 giờ, gấp 6 lần deadline 30 phút.

    Con số này CHƯA CÓ trong đặc tả, và nó quyết định mạng có khởi động được
    hay không — giống hệt cách 140/56.115 hợp đồng quyết định mạng có lãi không.
    """
    return n_shards * r * (cooldown + 1)


def min_workers_for_cap(r: int = WORKER_REDUNDANCY_R, ratio: float = WORKER_SLOT_CAP_RATIO) -> int:
    """Số worker tối thiểu để trần CỐ ĐỊNH ràng buộc. Với trần thích ứng thì
    không còn cần, nhưng giữ lại để so sánh và để test hồi quy."""
    return math.ceil(r / ratio) if ratio > 0 else 0


def cap_is_binding(n_workers: int, r: int = WORKER_REDUNDANCY_R,
                   ratio: float = WORKER_SLOT_CAP_RATIO) -> bool:
    return n_workers >= min_workers_for_cap(r, ratio)


# ═══════════════════════════════════════════════════════════════════════════
# 3. XỔ SỐ
# ═══════════════════════════════════════════════════════════════════════════


def worker_lottery(
    beacon: bytes,
    shard: int,
    pool: list[WorkerEntry],
    *,
    deadline: int,
    r: int = WORKER_REDUNDANCY_R,
    assigned_count: dict[bytes, int] | None = None,
    total_cells: int = 1,
    cooldown: int = 0,
    stats: LotteryStats | None = None,
) -> list[WorkerEntry]:
    """Chọn r worker phục vụ mảnh `shard` ở deadline này.

    Trả về đối tượng `WorkerEntry` chứ không phải id, để người gọi cập nhật
    trạng thái xoay vòng ngay — quên bước đó là bộ lọc ② mất tác dụng im lặng.
    """
    st = stats if stats is not None else LotteryStats()
    st.pool = len(pool)
    if not pool:
        return []

    # BẪY PYTHON: `assigned_count or {}` LOẠI BỎ dict rỗng do người gọi truyền
    # vào, vì dict rỗng là falsy. Mọi cập nhật rơi vào dict tạm rồi mất, trần
    # im lặng ngừng hoạt động, và worker giàu lại ăn hết ô — đúng thứ trần sinh
    # ra để chặn. Phải so với None.
    if assigned_count is None:
        assigned_count = {}

    cap = max(1, int(total_cells * adaptive_cap_ratio(len(pool), r)))

    # ── ① LỌC SỐNG  [CHỐT F3] ────────────────────────────────────────────
    live = [w for w in pool if w.is_live(deadline)]
    st.dropped_suspended = len(pool) - len(live)
    if len(live) < r:
        live = list(pool)  # thà giao cho worker đang bị nghi còn hơn bỏ trống ô

    # ── ② LỌC XOAY VÒNG  [CHỐT F2] ───────────────────────────────────────
    free = [w for w in live if w.is_free(deadline, cooldown)]
    st.dropped_cooldown = len(live) - len(free)
    if len(free) < r:
        free = list(live)
        st.relaxed_cooldown = True

    # ── ③ LỌC TRẦN  [CHỐT F1-c] ──────────────────────────────────────────
    eligible = [w for w in free if assigned_count.get(w.worker_id, 0) < cap]
    st.dropped_cap = len(free) - len(eligible)
    if len(eligible) < r:
        eligible = list(free)
        st.relaxed_cap = True

    # ── RÚT THĂM CÓ TRỌNG SỐ THEO CỌC, KHÔNG HOÀN LẠI ────────────────────
    chosen: list[WorkerEntry] = []
    remaining = list(eligible)
    for i in range(min(r, len(remaining))):
        total = sum(w.stake_wei for w in remaining)
        if total <= 0:
            chosen.append(remaining.pop(0))
            continue
        x = int.from_bytes(
            keccak(beacon, shard.to_bytes(4, "little"), i.to_bytes(2, "little"))[:16], "little"
        ) % total
        acc = 0
        for idx, w in enumerate(remaining):
            acc += w.stake_wei
            if acc > x:
                chosen.append(remaining.pop(idx))
                break

    for w in chosen:
        assigned_count[w.worker_id] = assigned_count.get(w.worker_id, 0) + 1
        w.last_assigned_deadline = deadline
    st.chosen = len(chosen)
    return chosen


# ═══════════════════════════════════════════════════════════════════════════
# 4. CẬP NHẬT TÍNH SỐNG
# ═══════════════════════════════════════════════════════════════════════════


def record_outcome(w: WorkerEntry, delivered: bool, deadline: int,
                   miss_threshold: int = DEFAULT_MISS_THRESHOLD,
                   suspension: int = DEFAULT_SUSPENSION_DEADLINES) -> None:
    """[CHỐT F3] Ghi nhận worker có nộp ChildProof không.

    NGUỒN SỰ THẬT: chứng cứ phủ đầy đủ ở tầng aggregator (§J.2.2) cho biết ô nào
    có ChildProof, ô nào không. Không cần nhịp tim on-chain, không cần giao dịch
    thêm — tính sống là sản phẩm phụ của cơ chế đã có.

    Nộp được thì bộ đếm reset. Bỏ liên tiếp đủ ngưỡng thì đình chỉ có thời hạn,
    và hết hạn là vào lại bể với bộ đếm sạch.
    """
    if delivered:
        w.consecutive_misses = 0
        return
    w.consecutive_misses += 1
    if w.consecutive_misses >= miss_threshold:
        w.suspended_until_deadline = deadline + suspension
        w.consecutive_misses = 0
