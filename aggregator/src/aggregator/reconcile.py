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

    cell_expected: dict[tuple[int, int], int] = field(default_factory=dict)
    """(deadline, mảnh) → |E_cell| mà các bản ChildProof của ô đó khai.

    [SỬA — nhận xét phản biện P0.3] Giữ riêng theo Ô, không cộng dồn thành một
    tổng. Cộng dồn thì một ô khai thừa bù được cho một ô khai thiếu, và tổng
    vẫn khớp.
    """

    stats: ReconcileStats = field(default_factory=ReconcileStats)


class CardinalityMismatch(RuntimeError):
    """Bản số phán quyết không khớp tập kỳ vọng.

    ── LỖ HỔNG PHÉP KIỂM NÀY ĐÓNG  [SỬA — nhận xét phản biện P0.3] ─────────

    Bản trước chỉ kiểm `num_verified > 0` rồi về sau là
    `num_verified == expectedDealCount`, trong đó num_verified = len(leaves).

    Cả hai đều KHÔNG chặn được:

      · một ô xét 3 trong 13 hợp đồng rồi trả về — ô vẫn tính là "đã phủ"
      · một ô nhồi thêm hợp đồng ngoài phạm vi để bù cho ô khác trả thiếu,
        giữ cho TỔNG vẫn khớp
      · hai ChildProof của cùng một ô dựng từ hai sổ khác nhau

    Phép kiểm đúng phải theo TỪNG Ô, và phải so với |E_cell| lấy từ sổ chứ
    không phải với số lá mà worker tự sinh ra.
    """


def reconcile_shard_results(results: list) -> EpochVerdicts:
    """Gộp nhiều ShardResult, kể cả nhiều bản của cùng một ô, theo sức nặng bằng cớ."""
    out = EpochVerdicts()
    for res in results:
        out.stats.childproofs_seen += 1
        cell = (res.deadline, res.shard)
        out.covered_cells.add(cell)
        out.covered_shards.add(res.shard)

        # ── Hai bản của CÙNG một ô phải khai CÙNG |E_cell| ──────────────
        #
        # Cả hai worker đều dựng E_cell từ sổ thành viên đã đối chiếu
        # snapshot_id, nên nếu trung thực thì con số phải trùng. Lệch nhau
        # nghĩa là ít nhất một bên dùng sổ khác — hoặc bịa.
        prev_exp = out.cell_expected.get(cell)
        if prev_exp is None:
            out.cell_expected[cell] = res.expected_count
        elif prev_exp != res.expected_count:
            raise CardinalityMismatch(
                f"ô {cell}: hai ChildProof khai {prev_exp} và "
                f"{res.expected_count} hợp đồng kỳ vọng"
            )

        # ── Số phán quyết trả về phải ĐÚNG BẰNG |E_cell| ────────────────
        #
        # Thiếu: worker xét một phần rồi trả về.
        # Thừa : worker nhồi hợp đồng ngoài ô mình để bù cho ô khác.
        if len(res.verdicts) != res.expected_count:
            raise CardinalityMismatch(
                f"ô {cell}: trả về {len(res.verdicts)} phán quyết "
                f"nhưng khai {res.expected_count} hợp đồng kỳ vọng"
            )
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
