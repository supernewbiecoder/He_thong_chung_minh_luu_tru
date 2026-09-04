"""
[SPEC §G.2] Chứng minh phủ đầy đủ — thay đổi lớn nhất của v2

 ── VẤN ĐỀ NÓ GIẢI ───────────────────────────────────────────────────────

 Guest chỉ thấy thứ host trình. Nếu host giấu một blob rồi khai ABSENT, guest
 không có cách nào biết. Bản v1 vá bằng cơ chế tranh chấp lạc quan, và cơ chế
 đó có ba nhược điểm: cần giả định "ít nhất một watchtower trung thực và đang
 thức", có độ trễ hai epoch cho MỌI epoch kể cả khi không ai gian, và phải giải
 câu "tranh chấp thắng rồi thì sao".

 ── CÁCH GIẢI ────────────────────────────────────────────────────────────

 NMT của Celestia lưu minNS/maxNS ở mỗi nút, nên chứng minh được không chỉ
 "share này thuộc namespace X" mà cả "đây là TOÀN BỘ share thuộc namespace X
 trong block này", kể cả khi tập đó rỗng.

 Guest TỰ DỰNG LẠI data_root từ các gốc hàng/cột — không nhận từ host — rồi
 kiểm đường lên DataRootTupleRoot mà Blobstream đã chứng thực.

 ── HỆ QUẢ ───────────────────────────────────────────────────────────────

   ABSENT           từ lời khai  →  KẾT LUẬN ĐƯỢC CHỨNG MINH
   watchtower       rời khỏi giả định an toàn §A.2.2
   disputeAbsent    bỏ hẳn, cùng cọc tranh chấp và cửa sổ Δ
   rút tiền         ngay sau finalizeEpoch, không chờ 2 epoch

 ── CHI PHÍ ──────────────────────────────────────────────────────────────

 411.200 sha256 mỗi cửa sổ ở trường hợp xấu nhất — MỘT LẦN cho cả mảnh, không
 phải một lần mỗi hợp đồng. Với ô 625 hợp đồng nó chiếm 0,006–0,12 %, tức nhiễu.
 Và spam KHÔNG làm nó bùng nổ: có trần cứng do trần block Celestia.
"""

from __future__ import annotations

from dataclasses import dataclass

from engram_common.blob import ObservedBlob
from engram_common.constants import COVERAGE_SHA256_PER_WINDOW, DATA_SQUARE_ROOTS_MAX
from engram_common.crypto import keccak, merkle_root


@dataclass(frozen=True)
class CoverageProof:
    """Cam kết rằng guest đã xét ĐÚNG tập blob có mặt trong namespace và cửa sổ.

    [CHỐT D3] Bản mô phỏng KHÔNG dựng NMT thật. Nó cam kết vào vị trí (chiều
    cao, chỉ số) của mọi blob quan sát được, và ĐẾM chi phí sha256 theo công
    thức thật. Cấu trúc và chi phí là thật; phép chứng minh mật mã là mô hình.

    Điều mock KHÔNG chứng minh được: rằng Celestia thật sự cho phép chứng minh
    phủ đầy đủ. Chỉ giai đoạn 2 của docs/KIEM_THU.md mới chứng minh được.
    """

    namespace: bytes
    height_start: int
    height_end: int
    n_blobs_seen: int
    commitment: bytes
    sha256_ops: int

    def cycles(self, sha_cycles: int) -> int:
        return self.sha256_ops * sha_cycles


def prove_coverage(
    namespace: bytes, blobs: list[ObservedBlob], height_start: int, height_end: int
) -> CoverageProof:
    """Thuật toán 5 — ProveCoverage.

    Cam kết vào TOÀN BỘ blob quan sát được, sắp theo (chiều cao, chỉ số) để tất
    định. Guest sau đó chỉ được xét đúng tập này — không thêm, không bớt.
    """
    ordered = sorted(blobs, key=lambda b: b.position)
    leaves = [
        keccak(b.height.to_bytes(8, "little"), b.index.to_bytes(4, "little"), b.signer)
        for b in ordered
    ]
    n_blocks = max(0, height_end - height_start)

    # Chi phí thật: mỗi block cần dựng lại data_root từ 2048 gốc hàng/cột
    # (2047 phép băm) cộng 9 phép cho đường tuple. Trần cứng 411.200.
    ops = min(COVERAGE_SHA256_PER_WINDOW, n_blocks * (DATA_SQUARE_ROOTS_MAX - 1 + 9))

    return CoverageProof(
        namespace=namespace,
        height_start=height_start,
        height_end=height_end,
        n_blobs_seen=len(ordered),
        commitment=merkle_root(leaves),
        sha256_ops=ops,
    )
