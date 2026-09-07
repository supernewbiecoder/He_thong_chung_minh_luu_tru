"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §H.1.6]  Cầu dao  ·  [CHỐT C1-b]  Ngưỡng worker tối thiểu
═══════════════════════════════════════════════════════════════════════════════

 Cơ chế phạt giả định các lỗi ĐỘC LẬP. Sự cố hạ tầng thì TƯƠNG QUAN: Celestia
 nghẽn thì MỌI nút cùng lỡ cửa sổ. Không có cầu dao, một sự cố 20 phút ghi
 NONE cho hàng nghìn hợp đồng cùng lúc.

 ── NHƯNG CẦU DAO CHỈ AN TOÀN KHI MẠNG ĐỦ LỚN  [CHỐT C1-b] ────────────────

 Ở mạng nhỏ, kẻ xấu DoS vài máy là hạ tỉ lệ phủ xuống dưới θ và VOID cả epoch
 — BIẾN CƠ CHẾ BẢO VỆ THÀNH CÔNG CỤ TẤN CÔNG rẻ tiền.

 Nên cầu dao chỉ bật khi:

     n_workers >= S_ns · r · (cooldown + 1)      = 224 ở N=10.000

 Dưới ngưỡng thì θ KHÔNG kích hoạt, và epoch được phán quyết bình thường.
 Chấp nhận phán quyết ở mạng nhỏ còn hơn để một cơ chế IM LẶNG KHÔNG HOẠT ĐỘNG
 tạo cảm giác an toàn giả.

 Cùng lý do đã dẫn tới trần khe thích ứng ở §A.4.3, và cùng bài học: một cơ chế
 bảo vệ không ràng buộc được thì tệ hơn không có, vì nó dạy người vận hành bỏ
 qua cảnh báo.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from dataclasses import dataclass

from engram_common.constants import CIRCUIT_BREAKER_THETA, WORKER_REDUNDANCY_R


@dataclass(frozen=True)
class BreakerResult:
    """Kết quả đánh giá cầu dao cho một epoch."""

    tripped: bool
    coverage_ratio: float
    threshold_met: bool
    n_workers: int
    required_workers: int
    reason: str

    @property
    def epoch_is_void(self) -> bool:
        return self.tripped


def evaluate(
    *,
    covered_cells: int,
    expected_cells: int,
    n_workers: int,
    n_shards: int,
    cooldown: int,
    r: int = WORKER_REDUNDANCY_R,
    theta: float = CIRCUIT_BREAKER_THETA,
) -> BreakerResult:
    """Cầu dao có nên nhả không.

    Trả về `tripped=True` nghĩa là epoch thành VOID: không thưởng, không phạt,
    ký quỹ không tiêu. Sự cố hạ tầng không được biến thành hình phạt hàng loạt.

    ── HAI ĐIỀU KIỆN, CẢ HAI ĐỀU CẦN ────────────────────────────────────────

    ① tỉ lệ phủ < θ            — có vẻ như sự cố diện rộng
    ② mạng đủ worker           — nếu không thì chính cầu dao là lỗ hổng

    Thiếu ② mà vẫn nhả thì kẻ xấu DoS vài máy là VOID được cả epoch.
    """
    ratio = covered_cells / max(1, expected_cells)
    required = n_shards * r * (cooldown + 1)
    threshold_met = n_workers >= required

    if ratio >= theta:
        return BreakerResult(False, ratio, threshold_met, n_workers, required,
                             f"phủ {ratio:.1%} ≥ θ={theta:.0%}, bình thường")

    if not threshold_met:
        # Phủ thấp NHƯNG mạng quá nhỏ để tin vào tín hiệu đó.
        return BreakerResult(
            False, ratio, threshold_met, n_workers, required,
            f"phủ {ratio:.1%} < θ nhưng mạng chỉ có {n_workers}/{required} worker — "
            f"KHÔNG nhả cầu dao, vì dưới ngưỡng thì chính nó là công cụ tấn công",
        )

    return BreakerResult(
        True, ratio, threshold_met, n_workers, required,
        f"phủ {ratio:.1%} < θ={theta:.0%} với {n_workers} worker — epoch VOID",
    )
