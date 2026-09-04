"""
[SPEC §F.2.3] Gộp epoch  ·  [CHỐT B4-a] [SPEC §J.2.2] Phủ đầy đủ tầng aggregator
"""

from __future__ import annotations

from dataclasses import dataclass

from engram_common.blob import BlobKind, build_namespace
from engram_common.clock import PublicValues
from engram_common.constants import GROTH16_PROOF_BYTES
from engram_common.crypto import keccak, merkle_root
from engram_common.verdict import Verdict

from .reconcile import EpochVerdicts, reconcile_shard_results


@dataclass(frozen=True)
class SettlementLeaf:
    """[SPEC §D.1.6] Một dòng phán quyết cho đúng một hợp đồng trong đúng một epoch.

    Là VÉ RÚT TIỀN. Hợp đồng EVM không tự phân phối; ai muốn nhận thì cầm lá này
    cùng đường Merkle lên nộp.

    Guest SP1 TỰ TÍNH lá từ biến verdict bên trong mạch — host không nhận lá từ
    ngoài rồi đưa vào, nên không sửa được phán quyết sau khi zkVM đã chạy xong.
    """

    provider_id: bytes
    deal_id: bytes
    verdict: Verdict
    challenges_total: int
    challenges_passed: int
    reward_wei: int
    slash_wei: int

    def digest(self) -> bytes:
        return keccak(
            self.provider_id,
            self.deal_id,
            bytes([int(self.verdict)]),
            self.challenges_total.to_bytes(4, "little"),
            self.challenges_passed.to_bytes(4, "little"),
            self.reward_wei.to_bytes(32, "little"),
            self.slash_wei.to_bytes(32, "little"),
        )


class CoverageGapError(RuntimeError):
    """[CHỐT B4-a] Aggregator KHÔNG được nộp khi thiếu ChildProof của một mảnh.

    Đây là bản vá cho §J.2.2 — lỗ nghiêm trọng thứ hai. Không có nó, aggregator
    im lặng bỏ một ChildProof, mảnh đó thành UNCOVERED, các hợp đồng trong mảnh
    nhận NONE, và aggregator KHÔNG MẤT GÌ.

    §G.2 đã đóng lỗ này ở TẦNG WORKER. Đóng một nửa rồi để nửa kia hở thì phần
    bảo mật mất tính nhất quán — người phản biện sẽ hỏi đúng câu "thế còn tầng
    aggregator?".

    Cách đóng: mọi ChildProof PHẢI lên DA (kind=02), và guest aggregator PHẢI
    chứng minh phủ đầy đủ trên namespace đó, đúng như worker làm với kind=01.
    Chi phí đã biết: 4,31–67,94 $/ngày toàn mạng.
    """


def aggregate_epoch(
    *,
    epoch: int,
    chain_id: int,
    shard_results: list,
    expected_shards: set[int],
    expected_deadlines: int,
    prev_state_root: bytes,
    da_commitment: bytes,
    da_nonce: int,
    submitter: bytes,
    storage_vk_digest: bytes,
    snapshot_id: bytes,
    require_full_coverage: bool = True,
) -> tuple[PublicValues, bytes, list[SettlementLeaf]]:
    """Gộp cả epoch thành 296 byte public values + bằng chứng Groth16 356 byte."""

    ev: EpochVerdicts = reconcile_shard_results(shard_results)

    # [CHỐT B4-a] Phủ đầy đủ ở TẦNG AGGREGATOR.
    if require_full_coverage:
        missing = expected_shards - ev.covered_shards
        expected_cells = len(expected_shards) * expected_deadlines
        if missing:
            raise CoverageGapError(f"thiếu ChildProof của mảnh {sorted(missing)}")
        if ev.stats.cells_seen < expected_cells:
            raise CoverageGapError(
                f"thiếu ChildProof: thấy {ev.stats.cells_seen}, cần {expected_cells}"
            )

    # Guest TỰ TÍNH results_root từ biến verdict — không nhận từ host.
    leaves: list[SettlementLeaf] = []
    for (pid, did), v in sorted(ev.verdicts.items()):
        leaves.append(
            SettlementLeaf(
                provider_id=pid,
                deal_id=did,
                verdict=v,
                challenges_total=16,
                challenges_passed=16 if v is Verdict.PASS else 0,
                reward_wei=10**12 if v is Verdict.PASS else 0,
                slash_wei=10**13 if v is Verdict.FAIL else 0,
            )
        )
    results_root = merkle_root([lf.digest() for lf in leaves])

    # [SPEC §J.1.1] Chuỗi trạng thái — mọi trường quan trọng phải nằm trong đó,
    # nếu không chúng có thể đổi mà không ai phát hiện khi kiểm lại từ đầu.
    new_state_root = keccak(
        prev_state_root,
        epoch.to_bytes(8, "little"),
        results_root,
        da_commitment,
        snapshot_id,
    )

    pv = PublicValues(
        epoch=epoch,
        batch_root=merkle_root([r.results_root for r in shard_results]),
        da_commitment=da_commitment,
        da_nonce=da_nonce,
        results_root=results_root,
        results_data_root=keccak(b"RESULTS_DA", results_root),
        storage_vk_digest=storage_vk_digest,
        snapshot_id=snapshot_id,
        submitter=submitter,
        prev_state_root=prev_state_root,
        new_state_root=new_state_root,
        num_verified=len(leaves),
    )

    # [CHỐT D3] Bằng chứng giả có ĐÚNG kích thước thật, nên calldata và gas THẬT.
    proof = bytes(GROTH16_PROOF_BYTES)
    return pv, proof, leaves


def childproof_namespace(chain_id: int) -> bytes:
    """[CHỐT B4-a] Namespace cho ChildProof. Aggregator đọc TOÀN BỘ namespace này
    và chứng minh phủ đầy đủ, đúng như worker làm với namespace bundle."""
    return build_namespace(BlobKind.CHILD_PROOF, chain_id, 0)
