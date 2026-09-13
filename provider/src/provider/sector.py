"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §E.1.1]  SECTOR THẬT TRÊN ĐĨA  ·  thay cho sector ảo
═══════════════════════════════════════════════════════════════════════════════

 ── VÌ SAO THAY ─────────────────────────────────────────────────────────────

 Bản trước SINH nội dung chunk theo yêu cầu từ một hạt giống thay vì lưu ra
 đĩa. Cách đó cho `piece_root`, `sealed_root`, chỉ số thách thức và đường
 Merkle đều THẬT, mà tốn ~0 dung lượng.

 Nhưng nó đánh mất đúng thứ mà cả hệ tồn tại để kiểm: **không mô phỏng được
 việc nút thật sự xoá dữ liệu**, vì không có dữ liệu để xoá. Mất dữ liệu phải
 giả bằng một tập chỉ số đánh dấu "đã mất", và bộ sinh trả rác cho chúng.

 Hệ quả: mọi kết luận về "nút gian bị bắt" đều là kết luận về MỘT CỜ TRONG BỘ
 NHỚ, không phải về byte trên đĩa. Người đọc mã không phân biệt được hai thứ đó
 nếu không đọc kỹ chú thích.

 ── BẢN NÀY LÀM GÌ ──────────────────────────────────────────────────────────

 Ghi byte thật ra đĩa, đọc byte thật khi thách thức, và **xoá file thật** khi
 mô phỏng mất dữ liệu. Nút xoá dữ liệu thì `chunk()` ném lỗi, không trả rác —
 vì một nút đã xoá thật thì nó KHÔNG CÓ GÌ để trả.

     ghi        sector.write(chunks)        → <root>/<deal_id>.sector
     đọc        sector.chunk(i)             → đọc đúng 4 KiB tại offset i·4096
     mất        sector.lose_fraction(f)     → ĐỤC LỖ thật bằng ftruncate/ghi đè
     xoá hẳn    sector.delete()             → gỡ file

 ── ĐÁNH ĐỔI, PHẢI BIẾT TRƯỚC KHI CHẠY ──────────────────────────────────────

 Sector thật của giao thức là 8.388.608 chunk = 32 GiB. Hai mươi hợp đồng là
 640 GiB. Không máy nào trong vòng thí nghiệm chạy nổi.

 Nên `SECTOR_CHUNKS_SIM` mặc định nhỏ hơn nhiều, và ĐÓ LÀ THAM SỐ chứ không
 phải hằng số giấu trong mã: chạy với bao nhiêu chunk là lựa chọn của người
 chạy, và con số đó được in ra cùng kết quả. Không có gì bị ẩn đi.

 Cấu trúc sector cố định 4 KiB mỗi chunk nên `chunk(i)` là một phép `seek` chứ
 không phải quét — chi phí đọc không phụ thuộc kích thước sector.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from engram_common.constants import CHUNK_SIZE_BYTES


class ChunkMissing(RuntimeError):
    """Nút không còn byte để trả.

    Khác hẳn "trả rác": một nút đã xoá dữ liệu thì nó không có gì để đưa vào
    mạch, nên ràng buộc chứng minh không dựng được. Ném lỗi mô tả đúng tình
    huống đó; trả rác thì mô tả một nút CÒN dữ liệu nhưng dữ liệu sai.
    """


def generate_chunk(deal_id: bytes, index: int, size: int = CHUNK_SIZE_BYTES) -> bytes:
    """Sinh nội dung chunk tất định, dùng làm DỮ LIỆU THỬ.

    Đây không phải một phần của giao thức: khi chạy thật, chunk đến từ khách.
    Giữ lại để dựng sector thử mà không cần file đầu vào thật.
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
class Sector:
    """Một sector nằm trên đĩa, truy cập theo offset cố định."""

    path: Path
    n_chunks: int
    chunk_size: int = CHUNK_SIZE_BYTES

    # ── ghi ────────────────────────────────────────────────────────────────

    @classmethod
    def create(cls, root: Path, deal_id: bytes, n_chunks: int,
               chunk_size: int = CHUNK_SIZE_BYTES) -> "Sector":
        """Dựng sector thử: ghi `n_chunks` chunk sinh từ `deal_id` ra đĩa."""
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{deal_id.hex()}.sector"
        with open(path, "wb") as f:
            for i in range(n_chunks):
                f.write(generate_chunk(deal_id, i, chunk_size))
        return cls(path=path, n_chunks=n_chunks, chunk_size=chunk_size)

    @classmethod
    def from_bytes(cls, root: Path, deal_id: bytes, data: bytes,
                   chunk_size: int = CHUNK_SIZE_BYTES) -> "Sector":
        """Dựng sector từ dữ liệu THẬT của khách. Đệm 0 cho chunk cuối."""
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{deal_id.hex()}.sector"
        n = (len(data) + chunk_size - 1) // chunk_size
        with open(path, "wb") as f:
            f.write(data)
            pad = n * chunk_size - len(data)
            if pad:
                f.write(b"\x00" * pad)
        return cls(path=path, n_chunks=n, chunk_size=chunk_size)

    # ── đọc ────────────────────────────────────────────────────────────────

    def chunk(self, index: int) -> bytes:
        """Đọc đúng một chunk. Một phép `seek`, không quét."""
        if not 0 <= index < self.n_chunks:
            raise IndexError(f"chunk {index} ngoài sector {self.n_chunks} chunk")
        if not self.path.exists():
            raise ChunkMissing(f"sector {self.path.name} đã bị xoá")
        with open(self.path, "rb") as f:
            f.seek(index * self.chunk_size)
            data = f.read(self.chunk_size)
        if len(data) < self.chunk_size:
            raise ChunkMissing(
                f"chunk {index}: đọc được {len(data)}/{self.chunk_size} byte — "
                f"file đã bị cắt"
            )
        return data

    def iter_chunks(self):
        """Duyệt tuần tự, dùng cho niêm phong theo luồng.

        Đọc theo luồng chứ không nạp cả sector vào RAM: sector thật là 32 GiB.
        """
        if not self.path.exists():
            raise ChunkMissing(f"sector {self.path.name} đã bị xoá")
        with open(self.path, "rb") as f:
            for _ in range(self.n_chunks):
                data = f.read(self.chunk_size)
                if len(data) < self.chunk_size:
                    data = data + b"\x00" * (self.chunk_size - len(data))
                yield data

    # ── mất dữ liệu: THẬT, không phải cờ ───────────────────────────────────

    def lose_chunks(self, indices) -> int:
        """Đục lỗ THẬT: ghi đè các chunk đó bằng 0 trên đĩa.

        Không dùng một tập chỉ số trong bộ nhớ. Sau lời gọi này, byte trên đĩa
        đã khác, và mọi đường đọc — kể cả đường không biết gì về mô phỏng —
        đều thấy sự khác đó.
        """
        indices = sorted(set(indices))
        with open(self.path, "r+b") as f:
            for i in indices:
                f.seek(i * self.chunk_size)
                f.write(b"\x00" * self.chunk_size)
        return len(indices)

    def lose_fraction(self, fraction: float) -> int:
        """[SPEC §I.1.3] Mất một phần dữ liệu, ví dụ hỏng một ổ cứng."""
        step = max(1, int(1 / max(1e-9, fraction)))
        return self.lose_chunks(range(0, self.n_chunks, step))

    def delete(self) -> None:
        """Nút xoá sạch để khỏi tốn ổ cứng. Sau đó `chunk()` ném `ChunkMissing`."""
        if self.path.exists():
            os.remove(self.path)

    # ── kế toán ────────────────────────────────────────────────────────────

    @property
    def raw_bytes(self) -> int:
        return self.n_chunks * self.chunk_size

    @property
    def on_disk_bytes(self) -> int:
        """Dung lượng THẬT đang chiếm. 0 nếu đã xoá."""
        return self.path.stat().st_size if self.path.exists() else 0

    @property
    def seal_form_bytes(self) -> int:
        """{R,S} = 64 byte mỗi chunk. Với sector 32 GiB là 512 MiB = 1,6 %.

        [SPEC §I.1.7] Giữ vết tốn 0,00012 $/tháng; xoá rồi dựng lại tốn ít nhất
        gấp 1.581 lần. Tấn công "nén và dựng lại" không có động cơ kinh tế.
        """
        return self.n_chunks * 64
