"""
[SPEC UC-01] Chuẩn bị dữ liệu phía khách.

 ── YÊU CẦU BẮT BUỘC MÀ GIAO THỨC KHÔNG CƯỠNG CHẾ ĐƯỢC ───────────────────

 Engram xét từng hợp đồng ĐỘC LẬP. Nếu n bản có cùng piece_root — tức cùng nội
 dung byte — thì một bên nắm cả n nút chỉ cần lưu MỘT bản thô, cộng n bộ {R,S}
 mỗi bộ 1,6 %:

     32 GiB + 1,5 GiB   thay vì   96 GiB   →   tiết kiệm 66 %

 và vẫn qua mọi thách thức, vì bản nào cũng trả lời đúng. Khách trả tiền ba
 bản, nhận độ bền của một.

 Mã Reed–Solomon đóng lỗ này vì n_RS mảnh có nội dung KHÁC NHAU. Nhưng RS nằm
 NGOÀI PHẠM VI Engram và [KHÔNG MÔ PHỎNG] ở bản này — xem constants.py.

 Hàm dưới đây là công cụ để khách TỰ KIỂM, không phải ràng buộc giao thức.
"""

from __future__ import annotations

from dataclasses import dataclass

from engram_common.constants import CHUNK_SIZE_BYTES, SECTOR_PROFILES
from engram_common.crypto import merkle_proof, merkle_root, poseidon2_stub


@dataclass(frozen=True)
class PreparedPiece:
    piece_root: bytes
    n_chunks_real: int
    n_chunks_padded: int
    chunks: list[bytes]

    @property
    def padding_ratio(self) -> float:
        """[SPEC §E.2.1] Tỉ lệ đệm. QUAN TRỌNG: SpreadChallenge phải dùng
        `n_chunks_real`, KHÔNG dùng `n_chunks_padded`.

        Truyền số đã đệm thì thách thức rơi vào vùng toàn 0 — mà chunk toàn 0
        cho 133 limb toàn 0, nút sinh lại miễn phí không cần lưu gì. Khách 19 GiB
        đệm lên 32 GiB thì 41 % thách thức thành vô nghĩa, và xác suất bắt khi
        nút xoá 1/16 dữ liệu tụt từ 0,6439 xuống 0,4540.
        """
        return 1.0 - self.n_chunks_real / max(1, self.n_chunks_padded)


def prepare(data: bytes, sector: str = "tiny") -> PreparedPiece:
    """Chia dữ liệu thành chunk, đệm lên luỹ thừa 2, tính piece_root.

    Đệm để MỌI hợp đồng có cùng chiều cao cây, nhờ đó dùng chung một khoá xác
    minh. Không đệm thì mỗi kích thước dữ liệu là một mạch khác nhau, và ý tưởng
    "một khoá cho cả mạng" sụp.
    """
    prof = SECTOR_PROFILES[sector]
    chunks = [data[i : i + CHUNK_SIZE_BYTES].ljust(CHUNK_SIZE_BYTES, b"\0")
              for i in range(0, len(data), CHUNK_SIZE_BYTES)] or [bytes(CHUNK_SIZE_BYTES)]
    n_real = len(chunks)
    padded = list(chunks) + [bytes(CHUNK_SIZE_BYTES)] * (prof.chunks - n_real)
    return PreparedPiece(
        piece_root=merkle_root([poseidon2_stub(c) for c in padded], hasher=poseidon2_stub),
        n_chunks_real=n_real,
        n_chunks_padded=prof.chunks,
        chunks=padded,
    )


def assert_distinct_replicas(pieces: list[PreparedPiece]) -> None:
    """Công cụ khách TỰ KIỂM. KHÔNG phải ràng buộc giao thức — hợp đồng EVM
    không kiểm điều này và không kiểm được."""
    roots = [p.piece_root for p in pieces]
    if len(set(roots)) != len(roots):
        raise ValueError(
            "Các bản có piece_root trùng nhau. Một bên nắm nhiều nút sẽ khử trùng "
            "lặp bản thô và bạn mất phần lớn độ bền đã trả tiền. Xem UC-01."
        )


def witness_bytes(piece_root: bytes, provider_path: list[bytes], batch_path: list[bytes]) -> int:
    """[SPEC UC-02 ⑮] 1.088 byte khách giữ sau khi xoá 19 GiB."""
    return 32 + 32 * len(provider_path) + 32 * len(batch_path)
