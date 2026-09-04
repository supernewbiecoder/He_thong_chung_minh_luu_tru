"""
[SPEC §E.4.2] VerifyShard — chương trình guest worker chạy trong SP1.

 Một lần chạy xử lý ĐÚNG MỘT Ô (deadline, mảnh) và trả lời một câu:
 "trong mảnh này, ở deadline này, hợp đồng nào đạt, hợp đồng nào không,
 hợp đồng nào vắng mặt".

 ── TÍNH CHẤT QUAN TRỌNG NHẤT ────────────────────────────────────────────

 Vòng lặp chạy trên DANH SÁCH KỲ VỌNG lấy từ ảnh chụp, KHÔNG chạy trên thứ tải
 về. Nhờ vậy rác trên namespace không bao giờ chạm tới lệnh verify, và chi phí
 zkVM là hàm của N chứ không phải hàm của lượng rác.

 ── BA THỨ MẠCH TỰ TÍNH, KHÔNG NHẬN TỪ HOST  [SPEC §D.2.2] ───────────────

   storage_vk_digest   keccak256(vk_bytes) — hợp đồng so với hằng số ghim
   results_root        từ biến verdict bên trong mạch
   num_verified        tự đếm

 Vì tự tính nên host không sửa được sau khi mạch chạy xong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engram_common.blob import FilterStats, ObservedBlob, filter_blobs
from engram_common.constants import BUNDLE_SIZE_BYTES
from engram_common.costs import shard_cycles
from engram_common.crypto import keccak, merkle_root
from engram_common.verdict import Verdict

from .coverage import CoverageProof, prove_coverage


@dataclass(frozen=True)
class ExpectedDeal:
    """Một hợp đồng mà ảnh chụp nói PHẢI có bằng chứng ở deadline này."""

    provider_id: bytes
    deal_id: bytes
    sealed_root: bytes
    declared_unavailable: bool = False

    @property
    def key(self) -> tuple[bytes, bytes]:
        return (self.provider_id, self.deal_id)


@dataclass
class ShardResult:
    """ChildProof — đầu ra của một ô."""

    deadline: int
    shard: int
    verdicts: dict[tuple[bytes, bytes], Verdict] = field(default_factory=dict)
    coverage: CoverageProof | None = None
    filter_stats: FilterStats | None = None
    cycles: int = 0
    results_root: bytes = b""

    @property
    def n_pass(self) -> int:
        return sum(1 for v in self.verdicts.values() if v is Verdict.PASS)

    @property
    def n_fail(self) -> int:
        return sum(1 for v in self.verdicts.values() if v is Verdict.FAIL)

    @property
    def n_absent(self) -> int:
        return sum(1 for v in self.verdicts.values() if v is Verdict.ABSENT)


def verify_bundle(payload: bytes, expected: ExpectedDeal) -> bool:
    """[CHỐT D3] Thế cho `verify(storage_vk, ...)` thật.

    Bản thật xác minh bằng chứng Spartan với khoá xác minh 4,7 MB. Ở đây ta
    kiểm ĐỘ DÀI và một cấu trúc tối thiểu — đủ để phân biệt bundle hợp lệ với
    rác, và giữ nguyên chi phí mô hình 11,255e9 chu kỳ mỗi lần.

    Điều bản mô phỏng KHÔNG chứng minh: rằng Nova/Spartan đúng. Nó chứng minh
    GIAO THỨC XUNG QUANH đúng. Xem docs/KIEM_THU.md mục "không kiểm được".
    """
    if len(payload) != BUNDLE_SIZE_BYTES:
        return False
    # Bundle rác trong mô phỏng là toàn 0xff; bundle thật mang sealed_root ở đầu.
    return payload[:32] == expected.sealed_root[:32]


def verify_shard(
    *,
    deadline: int,
    shard: int,
    namespace: bytes,
    expected: list[ExpectedDeal],
    observed: list[ObservedBlob],
    signer_of: dict[bytes, bytes],
    height_start: int,
    height_end: int,
    sha_cycles: int,
) -> ShardResult:
    """Thuật toán 4 — VerifyShard.

    Thứ tự các bước là bắt buộc; xem __init__.py của gói này.
    """
    # ── BƯỚC 0: PHỦ ĐẦY ĐỦ  [SPEC §G.2] ──────────────────────────────────
    # Làm TRƯỚC mọi thứ khác. Nó cố định tập blob mà guest được phép xét, nên
    # host không thể giấu bớt rồi khai ABSENT.
    cov = prove_coverage(namespace, observed, height_start, height_end)

    # ── BƯỚC 1: LỌC, gồm LỌC THEO NGƯỜI KÝ  [SPEC §J.2.1] ────────────────
    expected_keys = {e.key for e in expected}
    kept, stats = filter_blobs(
        observed,
        expected_keys=expected_keys,
        signer_of=signer_of,
        deadline=deadline,
        shard=shard,
        max_payload=BUNDLE_SIZE_BYTES,
    )

    # ── BƯỚC 2: MERGE-JOIN trên DANH SÁCH KỲ VỌNG ────────────────────────
    # Lặp trên `expected`, KHÔNG lặp trên `observed`. Đây là điều khiến chi phí
    # là hàm của N chứ không phải hàm của lượng rác.
    verdicts: dict[tuple[bytes, bytes], Verdict] = {}
    n_verified = 0

    for e in sorted(expected, key=lambda x: x.key):
        blob = kept.get(e.key)

        if blob is None:
            # Không có blob nào MANG NGƯỜI KÝ KHỚP. Nhờ chứng cứ phủ đầy đủ,
            # đây là kết luận ĐƯỢC CHỨNG MINH chứ không phải lời khai.
            verdicts[e.key] = Verdict.ABSENT
            continue

        # Có blob người ký khớp → xác minh được, nên ra PASS hoặc FAIL.
        #
        # [SPEC §J.2.1] FAIL chỉ ra được ở nhánh này. Kẻ ngoài không vào được
        # nhánh này vì không có khoá Celestia của nút. Nút gian TỰ đăng blob
        # rác thì vẫn vào nhánh này — người ký khớp — và ra FAIL, đúng như phải.
        n_verified += 1
        ok = verify_bundle(blob.payload, e)
        verdicts[e.key] = Verdict.PASS if ok else Verdict.FAIL

    # ── BƯỚC 3: guest TỰ TÍNH results_root từ biến verdict ───────────────
    leaves = [
        keccak(k[0], k[1], bytes([int(v)]))
        for k, v in sorted(verdicts.items())
    ]

    return ShardResult(
        deadline=deadline,
        shard=shard,
        verdicts=verdicts,
        coverage=cov,
        filter_stats=stats,
        cycles=shard_cycles(n_verified, sha_cycles),
        results_root=merkle_root(leaves),
    )
