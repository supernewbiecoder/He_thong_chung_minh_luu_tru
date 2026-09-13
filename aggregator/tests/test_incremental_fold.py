"""[T4.1] Gấp dần theo deadline phải cho KẾT QUẢ GIỐNG HỆT gộp một lần.

Nếu hai đường cho hai kết quả thì cả hai đều đáng ngờ, nên đây là bài kiểm quan
trọng nhất của tính năng này.
"""

import sys, pathlib

for m in ("common", "worker", "aggregator"):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / m / "src"))

import pytest

from aggregator.aggregate import (
    aggregate_epoch, aggregate_epoch_incremental, fold_deadline,
    CoverageGapError,
)
from aggregator.reconcile import SnapshotMismatch
from worker.verify import ShardResult
from engram_common.verdict import Verdict

SO = b"\x06" * 32
D, S = 2, 2
BASE = dict(epoch=1, chain_id=1, deadlines_per_epoch=D, n_shards=S,
            prev_state_root=bytes(32), da_commitment=b"\xda" * 32, da_nonce=1,
            submitter=b"\x7e" * 20, storage_vk_digest=b"\x05" * 32)


def _o(deadline, shard, snapshot_id=SO):
    v = {(bytes([deadline % 251, shard, 0]) + bytes(17),
          bytes([shard, 0]) + bytes(30)): Verdict.PASS}
    return ShardResult(deadline=deadline, shard=shard, snapshot_id=snapshot_id,
                       expected_count=1, verdicts=v, results_root=bytes(32))


def _all():
    return [[_o(1_000_000 + d, s) for s in range(S)] for d in range(D)]


def test_gap_dan_cho_ket_qua_giong_gop_mot_lan():
    groups = _all()
    flat = [r for g in groups for r in g]

    pv1, _, leaves1 = aggregate_epoch(shard_results=flat, snapshot_id=SO, **BASE)

    folds = [
        fold_deadline(deadline=1_000_000 + d, snapshot_id=SO,
                      shard_results=groups[d], n_shards=S)
        for d in range(D)
    ]
    pv2, _, leaves2 = aggregate_epoch_incremental(folds=folds, **BASE)

    assert pv1.pack() == pv2.pack()
    assert [l.digest() for l in leaves1] == [l.digest() for l in leaves2]


def test_thieu_manh_bi_bat_NGAY_sau_deadline_do():
    """Đây là lợi ích chính ngoài độ trễ: biết sớm 20 giờ."""
    groups = _all()
    with pytest.raises(CoverageGapError, match="thiếu mảnh"):
        fold_deadline(deadline=1_000_000, snapshot_id=SO,
                      shard_results=groups[0][:-1], n_shards=S)


def test_childproof_lac_deadline_bi_bat():
    with pytest.raises(CoverageGapError, match="lọt vào phần gộp"):
        fold_deadline(deadline=1_000_000, snapshot_id=SO,
                      shard_results=[_o(1_000_001, 0)], n_shards=S)


def test_hai_phan_gop_dung_hai_so_bi_chan():
    """Các phần gộp cách nhau tới 24 giờ nên nguy cơ lệch sổ cao hơn gộp một lần."""
    groups = _all()
    f0 = fold_deadline(deadline=1_000_000, snapshot_id=SO,
                       shard_results=groups[0], n_shards=S)
    g1 = [_o(1_000_001, s, snapshot_id=b"\x07" * 32) for s in range(S)]
    f1 = fold_deadline(deadline=1_000_001, snapshot_id=b"\x07" * 32,
                       shard_results=g1, n_shards=S)
    with pytest.raises(SnapshotMismatch):
        aggregate_epoch_incremental(folds=[f0, f1], **BASE)
