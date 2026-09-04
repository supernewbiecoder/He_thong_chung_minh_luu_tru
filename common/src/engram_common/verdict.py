"""
[SPEC §D.1.6] Phán quyết  ·  [SPEC §H.1.4] Hoà giải theo sức nặng bằng cớ
"""

from __future__ import annotations

from enum import IntEnum


class Verdict(IntEnum):
    """Thứ tự giá trị CHÍNH LÀ thứ hạng bằng cớ — đừng đổi thứ tự.

    ── QUY TẮC HOÀ GIẢI: PASS ≻ FAIL ≻ NONE  [SPEC §H.1.4] ──────────────────

    Ra PASS hay FAIL đều PHẢI trưng ra một blob có trường người ký khớp — thứ
    kẻ ngoài không giả được vì đồng thuận Celestia áp đặt nó. Còn NONE chỉ là
    lời khai vắng mặt, không trưng gì.

    Hệ quả: CHỈ CẦN MỘT trong r worker trung thực là phán quyết đúng thắng.

    Quy tắc cũ — "tới trước thắng, hoà thì keccak nhỏ hơn" — SAI. Nó dựa trên
    giả định hai worker luôn cho cùng kết quả vì phán quyết là hàm tất định của
    dữ liệu DA. Giả định đó vỡ khi có blob mạo danh: worker thật trình blob
    đúng, worker xấu trình blob giả, cả hai ChildProof đều hợp lệ về mặt SP1
    nhưng khác phán quyết, và quy tắc keccak cho kẻ xấu thắng 50 %.
    """

    NONE = 0     # không có bằng cớ nào — mảnh không được phủ, hoặc epoch VOID
    ABSENT = 1   # ĐƯỢC CHỨNG MINH vắng mặt nhờ phủ đầy đủ §G.2
    FAIL = 2     # có blob người ký khớp, nhưng Spartan sai
    PASS = 3     # có blob người ký khớp và Spartan đúng

    @property
    def has_evidence(self) -> bool:
        """PASS và FAIL trưng ra được blob; ABSENT trưng ra được chứng cứ phủ."""
        return self is not Verdict.NONE


def reconcile(a: Verdict, b: Verdict) -> Verdict:
    """Hoà giải hai phán quyết cho CÙNG một hợp đồng từ hai worker khác nhau."""
    return a if a >= b else b
