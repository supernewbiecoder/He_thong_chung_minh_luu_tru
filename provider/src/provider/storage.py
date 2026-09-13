"""
[SPEC §E.1.1] Lưu trữ phía nút.

 Nút PHẢI giữ HAI thứ, và đây là điểm không thoả hiệp được:

     dữ liệu thô        32 GiB   — ràng buộc ③ buộc trình 133 limb THẬT
     dạng niêm phong    512 MiB  — {R_i}, {S_i}, 64 B mỗi chunk = 1,6 %

 ── [MỞ] SECTOR ẢO KHI MÔ PHỎNG ──────────────────────────────────────────

 Sector thật là 8.388.608 chunk = 32 GiB. Với 20 hợp đồng thì 640 GiB — không
 mô phỏng nổi.

 Cách giải: SINH nội dung chunk theo yêu cầu từ một hạt giống, thay vì lưu ra
 đĩa. Chunk thứ j của hợp đồng D luôn ra cùng nội dung, nên:

     piece_root, sealed_root      THẬT, tính được, kiểm được
     chỉ số thách thức            THẬT
     đường Merkle                 THẬT
     dung lượng đĩa dùng          ~0

 Cái mất: không mô phỏng được việc nút THẬT SỰ xoá dữ liệu — vì không có dữ
 liệu để xoá. Kịch bản mất dữ liệu vì thế mô phỏng bằng một tập chỉ số bị đánh
 dấu "đã mất", và bộ sinh trả về rác cho những chỉ số đó.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from engram_common.constants import CHUNK_SIZE_BYTES


def generate_chunk(deal_id: bytes, index: int, size: int = CHUNK_SIZE_BYTES) -> bytes:
    """Sinh nội dung chunk tất định từ (deal_id, index).

    Dùng cho mô phỏng thay cho việc lưu byte thật. Đây KHÔNG phải một phần của
    giao thức — khi chạy thật, chunk đến từ khách và nằm trên đĩa.
    """
    out = bytearray()
    counter = 0
    while len(out) < size:
        out += hashlib.blake2b(
            deal_id + index.to_bytes(8, "little") + counter.to_bytes(4, "little"),
            digest_size=64,
        ).digest()
        counter += 1
    return bytes(out[:size])


@dataclass
class DealStorage:
    """Dữ liệu nút giữ cho MỘT hợp đồng."""

    deal_id: bytes
    n_chunks: int
    lost_indices: set[int] = field(default_factory=set)
    r_values: list[bytes] = field(default_factory=list)
    s_chain: list[bytes] = field(default_factory=list)
    sealed_root: bytes = b""

    def chunk(self, index: int) -> bytes:
        """Đọc chunk. Nếu chỉ số nằm trong tập đã mất thì trả về rác — mô phỏng
        đúng hành vi của một nút mất dữ liệu: nó vẫn TRẢ LỜI được, nhưng ràng
        buộc ③ trong mạch sẽ bắt ra sai."""
        if index in self.lost_indices:
            return b"\x00" * CHUNK_SIZE_BYTES
        return generate_chunk(self.deal_id, index)

    def lose_fraction(self, fraction: float) -> int:
        """Mô phỏng mất một phần dữ liệu, ví dụ hỏng một ổ cứng.

        [SPEC §I.1.3] Xoá 1/16 dữ liệu bị bắt trong 1,55 ngày với C=16.
        """
        step = max(1, int(1 / max(1e-9, fraction)))
        self.lost_indices = set(range(0, self.n_chunks, step))
        return len(self.lost_indices)

    @property
    def seal_form_bytes(self) -> int:
        """{R,S} = 64 byte mỗi chunk. Với sector 32 GiB là 512 MiB = 1,6 %.

        [SPEC §I.1.7] Giữ nó tốn 0,00012 $/tháng. Xoá rồi dựng lại tốn ít nhất
        gấp 1.581 lần. Tấn công 'nén và dựng lại' KHÔNG CÓ ĐỘNG CƠ KINH TẾ.
        """
        return self.n_chunks * 64
