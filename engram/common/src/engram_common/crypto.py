"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §2 / §A.5.1-3]  Nguyên hàm  ·  [SPEC §E.2.1]  Dẫn xuất thách thức
═══════════════════════════════════════════════════════════════════════════════

 ── HAI TẦNG BĂM, KHÔNG ĐƯỢC TRỘN ─────────────────────────────────────────

 keccak256  ngoài mạch — cây batch, cây quyết toán, chuỗi trạng thái.
            Chọn vì hợp đồng EVM tính nó RẺ.

 Poseidon2  trong mạch — niêm phong, cây dữ liệu, cây niêm phong.
            Chọn vì nó rẻ TRONG MẠCH: làm việc trực tiếp trên phần tử trường
            thay vì trên bit. Cái giá là chậm hơn nhiều trên CPU thường —
            11,89 µs mỗi lần hoán vị, so với keccak256 dưới 1 µs.

 [CHỐT D3] Bản mô phỏng KHÔNG chạy Poseidon2 thật: nó dùng keccak256 làm thế
 thân và tính chi phí bằng mô hình (costs.py). Giá trị băm vì thế KHÔNG dùng
 để sinh bằng chứng thật được — nhưng cấu trúc cây, chỉ số thách thức, và mọi
 kích thước đều THẬT.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import hashlib
from typing import Iterable, Sequence

# ═══════════════════════════════════════════════════════════════════════════
# 1. BĂM
# ═══════════════════════════════════════════════════════════════════════════


def keccak(*parts: bytes) -> bytes:
    """[SPEC §2.1] Tầng ngoài mạch.

    Lưu ý: Python không có keccak256 chuẩn (sha3_256 là SHA-3, KHÁC keccak).
    Ở bản mô phỏng ta dùng sha3_256 làm thế thân — điều này CHẤP NHẬN ĐƯỢC vì
    ta không sinh bằng chứng thật, nhưng KHÔNG được đem ra so với giá trị do
    hợp đồng Solidity tính. Khi nối với chuỗi thật phải thay bằng pysha3 hoặc
    eth-hash.
    """
    h = hashlib.sha3_256()
    for p in parts:
        h.update(p)
    return h.digest()


def poseidon2_stub(*parts: bytes) -> bytes:
    """[SPEC §2.1] THẾ THÂN cho Poseidon2 trong mạch.

    [CHỐT D3] Không phải Poseidon2 thật. Chi phí thật được tính riêng ở
    costs.py bằng số đo 11,89 µs mỗi lần hoán vị. Hàm này chỉ để cấu trúc cây
    và chỉ số thách thức đúng.
    """
    h = hashlib.blake2b(digest_size=32)
    for p in parts:
        h.update(p)
    return h.digest()


# ═══════════════════════════════════════════════════════════════════════════
# 2. CÂY MERKLE  ·  [SPEC §2.3 / §A.5.2]
# ═══════════════════════════════════════════════════════════════════════════


def merkle_root(leaves: Sequence[bytes], hasher=keccak) -> bytes:
    """Gói một danh sách dài thành MỘT giá trị 32 byte.

    [SPEC §2.3] Số lá lẻ thì nhân đôi lá cuối. Danh sách rỗng trả về 32 byte 0.
    """
    if not leaves:
        return bytes(32)
    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hasher(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(leaves: Sequence[bytes], index: int, hasher=keccak) -> list[bytes]:
    """Đường đi từ lá lên gốc — các nút anh em dọc đường.

    Với 8.388.608 lá thì đường dài 23 nút = 736 byte, thay vì gửi cả danh sách.
    Đây là 23 trong 32 tầng của 1.088 byte nhân chứng mà khách giữ (§UC-02 ⑮).
    """
    if not leaves:
        return []
    level = list(leaves)
    idx = index
    path: list[bytes] = []
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        sib = idx ^ 1
        path.append(level[sib])
        level = [hasher(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return path


def merkle_verify(leaf: bytes, path: Iterable[bytes], index: int, root: bytes, hasher=keccak) -> bool:
    """Leo lại đường đi. Hướng rẽ theo BIT của chỉ số lá.

    Phải khớp bit-để-bit với `_merkleRoot` trong EngramManager.sol, nếu không
    bằng chứng hợp lệ ở một phía sẽ bị phía kia từ chối mà không có thông điệp
    lỗi rõ ràng.
    """
    node = leaf
    idx = index
    for sib in path:
        node = hasher(node, sib) if idx % 2 == 0 else hasher(sib, node)
        idx //= 2
    return node == root


# ═══════════════════════════════════════════════════════════════════════════
# 3. CÂY KHE THƯA  ·  [SPEC §D.1.2]
# ═══════════════════════════════════════════════════════════════════════════


class SlotTree:
    """`provider_root` — cây Merkle thưa CỐ ĐỊNH trên `capacity_slots` khe.

    Mỗi khe chứa `sealed_root` của một hợp đồng, hoặc 32 byte 0 nếu khe trống.

    ── VÌ SAO LÀ CÂY KHE CHỨ KHÔNG PHẢI CÂY PHẲNG TRÊN CHUNK ────────────────

    Bản v1 định nghĩa `provider_root` là gốc trên TẤT CẢ chunk của mọi hợp đồng.
    Cách đó có một vấn đề để ngỏ: đóng một hợp đồng làm ĐỔI CẢ CÂY, nên đường
    Merkle của mọi khách khác hỏng theo, và không ai biết phải cập nhật lúc nào.

    Cây khe cố định giải đúng chỗ đó. `capacity_slots` khai một lần và không đổi,
    nên HÌNH DẠNG cây ổn định. Đóng hợp đồng chỉ đặt một lá về 0. Đường Merkle
    của khách khác vẫn phải tính lại — nhưng tính từ dữ liệu công khai, tất định,
    ai cũng làm được bằng một vòng lặp.
    """

    def __init__(self, capacity_slots: int):
        if capacity_slots & (capacity_slots - 1):
            raise ValueError("capacity_slots phải là luỹ thừa của 2")
        self.capacity = capacity_slots
        self.slots: list[bytes] = [bytes(32)] * capacity_slots

    def set(self, slot_idx: int, sealed_root: bytes) -> None:
        self.slots[slot_idx] = sealed_root

    def clear(self, slot_idx: int) -> None:
        self.slots[slot_idx] = bytes(32)

    @property
    def root(self) -> bytes:
        return merkle_root(self.slots)

    def proof(self, slot_idx: int) -> list[bytes]:
        return merkle_proof(self.slots, slot_idx)

    @property
    def used(self) -> int:
        return sum(1 for s in self.slots if s != bytes(32))


# ═══════════════════════════════════════════════════════════════════════════
# 4. DẪN XUẤT THÁCH THỨC  ·  [SPEC §E.2.1]
# ═══════════════════════════════════════════════════════════════════════════


def spread_challenge(
    beacon: bytes, deal_id: bytes, count_challenges: int, offset: int, count_chunks: int
) -> list[int]:
    """Thuật toán 2 — SpreadChallenge.

    ── HAI TÍNH CHẤT, CẢ HAI ĐỀU CẦN ────────────────────────────────────────

    TRONG DẢI HỢP ĐỒNG. j luôn thuộc [offset, offset+count). Không có bước này,
    hợp đồng rút khỏi nút để lại vùng trống, và thách thức rơi vào đó sẽ PHẠT
    OAN — tỉ lệ phạt oan bằng đúng tỉ lệ vùng trống.

    RẢI ĐỀU. Mỗi khoảng n/C có đúng MỘT thách thức, nên xoá một khối liền không
    né được.

    ── MỘT CHI TIẾT DỄ SAI VÀ RẤT TỐN ───────────────────────────────────────

    `count_chunks` PHẢI là số chunk THẬT của khách, KHÔNG phải số chunk sau khi
    đệm lên luỹ thừa 2. Nếu truyền số đã đệm thì thách thức rơi vào vùng đệm
    toàn số 0 — mà chunk toàn 0 cho 133 limb toàn 0, nút sinh lại miễn phí
    không cần lưu gì.

    Khách 19 GiB đệm lên 32 GiB thì 41 % thách thức thành vô nghĩa: C hiệu dụng
    tụt từ 16 xuống 9,5, và xác suất bắt khi nút xoá 1/16 dữ liệu tụt từ 0,6439
    xuống 0,4540. Khách 1 GiB thì tụt còn 0,0308 — kém 21 lần.
    """
    if count_challenges <= 0 or count_chunks <= 0:
        return []
    bucket = max(1, count_chunks // count_challenges)
    out: list[int] = []
    for i in range(count_challenges):
        seed = poseidon2_stub(beacon, deal_id, i.to_bytes(4, "little"))
        pos = offset + i * bucket + (int.from_bytes(seed[:8], "little") % bucket)
        out.append(min(pos, offset + count_chunks - 1))
    return out


def derive_shard(deal_id: bytes, n_shards: int) -> int:
    """[SPEC §A.4.3] `shard = H(deal_id) mod S_ns`, CỐ ĐỊNH cả đời hợp đồng.

    Cố định chứ không xoay, khác với gán worker. Nếu mảnh đổi mỗi epoch thì nút
    phải theo dõi thêm một biến, và namespace không còn ổn định để đăng ký lắng
    nghe.
    """
    return int.from_bytes(keccak(deal_id)[:8], "little") % max(1, n_shards)


def derive_deadline(deal_id: bytes, deadlines_per_epoch: int) -> int:
    """[CHỐT E3] [SPEC §D.1.5] `deadline_idx = H(deal_id) mod D`, CỐ ĐỊNH cả đời.

    ── VÌ SAO ĐỔI KHỎI QUY TẮC CŨ ───────────────────────────────────────────

    Đặc tả v2 nói "chọn khung có ít hợp đồng nhất của nút đó, tính từ biến đếm
    on-chain". Đúng về mặt cân bằng tải, nhưng tốn một MẢNG ĐẾM trên chuỗi cho
    mỗi cặp (nút, deadline) — tức D ô lưu trữ mỗi nút, và một lần ghi mỗi lần
    openDeal.

    Băm chia dư cho cùng tính chất mà không tốn trạng thái nào:
      tất định   ai tính cũng ra cùng kết quả, không cần hỏi chuỗi
      cân bằng   băm rải đều, kỳ vọng N/D hợp đồng mỗi khung
      cố định    không đổi cả đời, nên nút lên lịch tài nguyên được

    Cái mất: cân bằng là KỲ VỌNG chứ không phải BẢO ĐẢM. Với N nhỏ có thể lệch
    vài hợp đồng giữa các khung. Không quan trọng, vì tải mỗi khung vốn đã nhỏ.
    """
    return int.from_bytes(keccak(b"ENGRAM_DEADLINE", deal_id)[:8], "little") % max(1, deadlines_per_epoch)


def derive_beacon(data_roots: Sequence[bytes]) -> bytes:
    """[SPEC §F.2.1] `beacon_d = H(data_root[h] ‖ … ‖ data_root[h−3])`.

    ── VÌ SAO TRỘN 4 BLOCK ──────────────────────────────────────────────────

    Người đề xuất block Celestia tại h_d chọn được thứ tự giao dịch, nên MÀI
    được `data_root[h_d]` để thách thức rơi vào chỗ nó còn giữ. Trộn 4 block
    liên tiếp buộc phải có BỐN người đề xuất liên tiếp cấu kết, và mỗi lần thử
    lại tốn một lần dựng square 128 MiB.

    Filecoin dùng đúng dạng phòng thủ này: randomness công bố trước khi deadline
    mở 20 epoch.
    """
    return keccak(*data_roots)
