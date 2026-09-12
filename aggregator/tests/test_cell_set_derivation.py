"""[SỬA P0.3] Tập ô kỳ vọng phải do aggregator DẪN XUẤT, không nhận từ host.

Bản trước nhận `expected_cells` làm tham số. Đó đúng là lỗ hổng mà §D.3 vá ở
tầng worker, chỉ lùi lên một tầng: host đưa vào một tập đã bớt một ô thì
`missing` rỗng, không ai báo lỗi, và các hợp đồng trong ô đó lặng lẽ không có
phán quyết — nút mất doanh thu, không ai phát hiện.
"""

import sys, pathlib, inspect

for m in ("common", "worker", "aggregator"):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / m / "src"))

import pytest

from aggregator.aggregate import aggregate_epoch, CoverageGapError
from worker.verify import ShardResult
from engram_common.verdict import Verdict

SO = b"\x06" * 32
D, S = 2, 2


def _o(deadline, shard, n=1):
    # khoá phải DUY NHẤT theo ô, nếu không các lá trùng nhau và Σ|E_cell| lệch
    v = {
        (bytes([deadline % 251, shard, i]) + bytes(17), bytes([shard, i]) + bytes(30)): Verdict.PASS
        for i in range(n)
    }
    return ShardResult(deadline=deadline, shard=shard, snapshot_id=SO,
                       expected_count=n, verdicts=v, results_root=bytes(32))


def _agg(results, **kw):
    base = dict(epoch=1, chain_id=1, shard_results=results,
                deadlines_per_epoch=D, n_shards=S,
                prev_state_root=bytes(32), da_commitment=b"\xda" * 32,
                da_nonce=1, submitter=b"\x7e" * 20,
                storage_vk_digest=b"\x05" * 32, snapshot_id=SO)
    base.update(kw)
    return aggregate_epoch(**base)


def _full():
    return [_o(1_000_000 + d, s) for d in range(D) for s in range(S)]


def test_khong_con_tham_so_expected_cells():
    """Chốt bằng chữ ký hàm: không thể truyền vào một tập đã bị bớt."""
    assert "expected_cells" not in inspect.signature(aggregate_epoch).parameters


def test_du_o_thi_qua():
    pv, _, leaves = _agg(_full())
    assert pv.num_verified == len(leaves) == D * S


def test_thieu_mot_o_bi_bat():
    with pytest.raises(CoverageGapError):
        _agg(_full()[:-1])


def test_o_ngoai_luoi_bi_bat():
    with pytest.raises(CoverageGapError):
        _agg(_full() + [_o(1_000_000 + 99, 0)])


def test_so_khac_public_values_bi_bat():
    from aggregator.reconcile import SnapshotMismatch
    with pytest.raises(SnapshotMismatch):
        _agg(_full(), snapshot_id=b"\x07" * 32)
