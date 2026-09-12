"""[SỬA P0.3] Chuỗi sổ phải khép kín từ ChildProof lên tới public values.

Góp ý của thầy nêu ba điều kiện cho mắt xích thứ tư, và bản trước chỉ có một:

  ① mỗi child proof bind với deadline, shard, snapshot_id, |E_cell|   ← THIẾU snapshot_id
  ② aggregator kiểm mỗi ô kỳ vọng xuất hiện ĐÚNG MỘT LẦN             ← có, nhưng tập ô nhận từ host
  ③ num_verified tính từ Σ|E_cell|, không nhận từ host                ← đã có

Vì sao ① không thay thế được bằng |E_cell|: bằng nhau về SỐ LƯỢNG không có
nghĩa là cùng một sổ. Hai sổ khác nhau vẫn cho ra cùng |E_cell|, và giữa các ô
khác nhau thì `expected_count` không ràng buộc gì cả.
"""

import sys, pathlib

for m in ("common", "worker", "aggregator"):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / m / "src"))

import pytest

from aggregator.reconcile import reconcile_shard_results, SnapshotMismatch
from worker.verify import ShardResult
from engram_common.verdict import Verdict

SO_A = b"\xaa" * 32
SO_B = b"\xbb" * 32


def _o(deadline, shard, snapshot_id, n=1):
    v = {(bytes([i]) * 20, bytes([i]) * 32): Verdict.PASS for i in range(n)}
    return ShardResult(
        deadline=deadline, shard=shard, snapshot_id=snapshot_id,
        expected_count=n, verdicts=v, results_root=bytes(32),
    )


def test_cung_mot_so_thi_qua():
    ev = reconcile_shard_results([_o(1, 0, SO_A), _o(1, 1, SO_A)])
    assert ev.snapshot_id == SO_A


def test_hai_o_dung_hai_so_khac_nhau_bi_chan():
    """Đây là lỗ mà `expected_count` KHÔNG bắt được: ô 0 dựng từ sổ epoch trước,
    ô 1 dựng từ sổ epoch này, Σ|E_cell| vẫn khớp con số on-chain."""
    with pytest.raises(SnapshotMismatch):
        reconcile_shard_results([_o(1, 0, SO_A), _o(1, 1, SO_B)])


def test_hai_ban_cua_cung_mot_o_dung_hai_so_bi_chan():
    with pytest.raises(SnapshotMismatch):
        reconcile_shard_results([_o(1, 0, SO_A), _o(1, 0, SO_B)])


def test_so_luong_bang_nhau_khong_du_de_ket_luan_cung_so():
    """Chốt lý do ① tồn tại: hai sổ khác nhau cho cùng |E_cell| = 3."""
    a, b = _o(1, 0, SO_A, n=3), _o(1, 0, SO_B, n=3)
    assert a.expected_count == b.expected_count
    with pytest.raises(SnapshotMismatch):
        reconcile_shard_results([a, b])
