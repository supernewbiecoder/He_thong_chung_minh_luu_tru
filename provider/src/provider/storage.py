"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §E.1.1]  Lưu trữ phía nút
═══════════════════════════════════════════════════════════════════════════════

 Nút PHẢI giữ HAI thứ, và đây là điểm không thoả hiệp được:

     dữ liệu thô        32 GiB   — ràng buộc ③ buộc trình 133 limb THẬT
     dạng niêm phong    512 MiB  — {R_i}, {S_i}, 64 B mỗi chunk = 1,6 %

 ── ĐÃ BỎ SECTOR ẢO ─────────────────────────────────────────────────────────

 Bản trước SINH nội dung chunk theo yêu cầu từ một hạt giống thay vì lưu ra
 đĩa, và mô phỏng mất dữ liệu bằng một TẬP CHỈ SỐ trong bộ nhớ.

 Cách đó đánh mất đúng thứ cả hệ tồn tại để kiểm: không có byte nào để xoá, nên
 "nút gian bị bắt" chỉ là kết luận về một cờ trong RAM.

 Giờ dữ liệu thô nằm trên đĩa qua `Sector`, mất dữ liệu là ĐỤC LỖ THẬT, và xoá
 sạch là gỡ file. Xem `sector.py`.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .sector import ChunkMissing, Sector, generate_chunk

__all__ = ["DealStorage", "Sector", "ChunkMissing", "generate_chunk"]


@dataclass
class DealStorage:
    """Dữ liệu nút giữ cho MỘT hợp đồng: sector thô trên đĩa + vết niêm phong."""

    deal_id: bytes
    n_chunks: int
    sector: Sector | None = None
    r_values: list[bytes] = field(default_factory=list)
    s_chain: list[bytes] = field(default_factory=list)
    sealed_root: bytes = b""

    @classmethod
    def create(cls, root: Path, deal_id: bytes, n_chunks: int) -> "DealStorage":
        """Dựng kho có sector THẬT trên đĩa."""
        sec = Sector.create(root, deal_id, n_chunks)
        return cls(deal_id=deal_id, n_chunks=n_chunks, sector=sec)

    @classmethod
    def from_bytes(cls, root: Path, deal_id: bytes, data: bytes) -> "DealStorage":
        """Dựng kho từ dữ liệu THẬT của khách."""
        sec = Sector.from_bytes(root, deal_id, data)
        return cls(deal_id=deal_id, n_chunks=sec.n_chunks, sector=sec)

    # ── đọc ────────────────────────────────────────────────────────────────

    def chunk(self, index: int) -> bytes:
        """Đọc một chunk từ đĩa.

        Ném `ChunkMissing` nếu nút đã xoá. KHÔNG trả rác: một nút đã xoá thật
        thì không có gì để đưa vào mạch, nên ràng buộc không dựng được. Trả rác
        sẽ mô tả sai tình huống — đó là nút CÒN dữ liệu nhưng dữ liệu hỏng.
        """
        if self.sector is None:
            raise ChunkMissing("kho chưa gắn sector")
        return self.sector.chunk(index)

    def iter_chunks(self):
        if self.sector is None:
            raise ChunkMissing("kho chưa gắn sector")
        return self.sector.iter_chunks()

    # ── mất dữ liệu ────────────────────────────────────────────────────────

    def lose_fraction(self, fraction: float) -> int:
        """[SPEC §I.1.3] Mất một phần dữ liệu. ĐỤC LỖ THẬT trên đĩa."""
        if self.sector is None:
            raise ChunkMissing("kho chưa gắn sector")
        return self.sector.lose_fraction(fraction)

    def delete_raw(self) -> None:
        """Nút xoá sạch dữ liệu thô để khỏi tốn ổ cứng, chỉ giữ vết niêm phong.

        Đây là tấn công "nén và dựng lại". Sau lời gọi này `chunk()` ném lỗi, và
        nút không sinh được bằng chứng — trừ khi nó dựng lại toàn bộ sector.
        """
        if self.sector is not None:
            self.sector.delete()

    # ── kế toán ────────────────────────────────────────────────────────────

    @property
    def raw_bytes(self) -> int:
        return self.sector.raw_bytes if self.sector else 0

    @property
    def on_disk_bytes(self) -> int:
        """Dung lượng THẬT đang chiếm. 0 sau khi xoá — kiểm được, không phải cờ."""
        return self.sector.on_disk_bytes if self.sector else 0

    @property
    def seal_form_bytes(self) -> int:
        """{R,S} = 64 byte mỗi chunk. Sector 32 GiB → 512 MiB = 1,6 %.

        [SPEC §I.1.7] Giữ vết tốn 0,00012 $/tháng; xoá rồi dựng lại tốn ít nhất
        gấp 1.581 lần. Tấn công "nén và dựng lại" không có động cơ kinh tế.
        """
        return self.n_chunks * 64
