"""
[SPEC §H.1.4] Hoà giải r worker  ·  [SPEC §J.2.1] nửa sau của bản sửa

 ── VÌ SAO QUY TẮC CŨ SAI ────────────────────────────────────────────────

 Bản trước hoà giải bằng "ChildProof nào tới trước; hoà thì lấy keccak nhỏ hơn",
 với lý do "cả hai đều cho cùng phán quyết vì phán quyết là hàm tất định của
 dữ liệu trên DA".

 Giả định đó VỠ khi có blob mạo danh: worker thật trình blob đúng, worker xấu
 trình blob giả, cả hai ChildProof đều hợp lệ về mặt SP1 nhưng KHÁC phán quyết.
 Quy tắc keccak khi đó cho kẻ xấu thắng 50 %.

 ── QUY TẮC ĐÚNG: PASS ≻ FAIL ≻ NONE ─────────────────────────────────────

 Ra PASS hay FAIL đều PHẢI trưng ra một blob có trường người ký khớp — thứ kẻ
 ngoài không giả được vì đồng thuận Celestia áp đặt nó. Còn NONE chỉ là lời
 khai vắng mặt, không trưng gì.

 Hệ quả: CHỈ CẦN MỘT trong r worker trung thực là phán quyết đúng thắng. Đó
 chính là điều mà dư thừa r=2 đáng lẽ phải cho, và quy tắc cũ không cho.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engram_common.verdict import Verdict, reconcile


@dataclass
class ReconcileStats:
    childproofs_seen: int = 0
    conflicts: int = 0
    upgraded_from_none: int = 0
    upgraded_to_pass: int = 0


@dataclass
class EpochVerdicts:
    """Phán quyết đã hoà giải cho cả epoch."""

    verdicts: dict[tuple[bytes, bytes], Verdict] = field(default_factory=dict)
    covered_cells: set[tuple[int, int]] = field(default_factory=set)
    """Tập ô (deadline, mảnh) có ÍT NHẤT MỘT ChildProof.

    ── PHÂN BIỆT PHỦ ĐẦY ĐỦ VỚI DƯ THỪA ────────────────────────────────────

    Đếm SỐ BẢN ChildProof là sai. Với r=2, một worker chết thì ô vẫn được phủ
    bởi worker còn lại — đó chính là điều dư thừa sinh ra để làm. Nếu phép kiểm
    đòi đủ r bản thì MỘT worker chết là void cả epoch, và r=2 thành vô dụng.

    Phủ đầy đủ hỏi: "mọi ô có ít nhất một ChildProof không?" — câu hỏi AN TOÀN.
    Dư thừa hỏi: "có mấy bản?" — câu hỏi TÍNH SỐNG. Hai câu khác nhau."""

    covered_shards: set[int] = field(default_factory=set)
    stats: ReconcileStats = field(default_factory=ReconcileStats)


def reconcile_shard_results(results: list) -> EpochVerdicts:
    """Gộp nhiều ShardResult, kể cả nhiều bản của cùng một ô, theo sức nặng bằng cớ."""
    out = EpochVerdicts()
    for res in results:
        out.stats.childproofs_seen += 1
        out.covered_cells.add((res.deadline, res.shard))
        out.covered_shards.add(res.shard)
        for key, v in res.verdicts.items():
            prev = out.verdicts.get(key)
            if prev is None:
                out.verdicts[key] = v
                continue
            if prev is not v:
                out.stats.conflicts += 1
                if prev is Verdict.NONE:
                    out.stats.upgraded_from_none += 1
                if v is Verdict.PASS or prev is Verdict.PASS:
                    out.stats.upgraded_to_pass += 1
            out.verdicts[key] = reconcile(prev, v)
    return out
