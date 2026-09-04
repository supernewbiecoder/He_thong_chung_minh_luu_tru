"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §G.1.2]  Bố cục namespace     ·  [SPEC §G.1.3]  Định dạng blob
 [SPEC §J.2.1]  Chống mạo danh blob  ·  [SPEC §G.1.4]  Thang lọc F0–F6
═══════════════════════════════════════════════════════════════════════════════

 Mô-đun này làm ba việc, và việc thứ ba là quan trọng nhất về mặt an toàn:

   1. Dựng namespace Celestia cho một mảnh
   2. Đóng gói / mở gói tiêu đề blob của Engram
   3. LỌC BLOB THEO NGƯỜI KÝ — đóng lỗ hổng §J.2.1

 ── VÌ SAO VIỆC THỨ BA TỒN TẠI ─────────────────────────────────────────────

 Cặp nhãn (provider_id, deal_id) là CÔNG KHAI trên chuỗi, và namespace Celestia
 KHÔNG CÓ CHỦ. Nên kẻ ngoài đăng được một blob mang đúng nhãn của nút P, ruột
 rác, giá 0,00009 $. Nếu worker lấy trúng blob rác thì P bị phạt dù làm đúng.

 Bản sửa dùng chính cấu trúc của Celestia: share phiên bản 1 chứa trường
 `signer` 20 byte, và ĐỒNG THUẬN CELESTIA TỰ KIỂM nó phải trùng người ký giao
 dịch. Kẻ ngoài không điền giả được. Lọc = so sánh 20 byte.

 Chi phí khi bị đổ 52,4 triệu blob rác:
     kiểm chữ ký ECDSA mọi blob  →  1,46 giờ CPU   (phương án ĐÃ LOẠI)
     lọc theo người ký           →  2,6 giây       ← nhanh hơn 2.000 lần
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .constants import (
    BlobKind,
    CELESTIA_GAS_PER_BLOB_BYTE,
    CELESTIA_MIN_GAS_PRICE_UTIA,
    CELESTIA_PFB_FIXED_GAS,
    CONT_SHARE_PAYLOAD,
    FIRST_SHARE_PAYLOAD_V1,
    NAMESPACE_ID_FREE_BYTES,
    SHARE_SIZE,
    SIGNER_SIZE,
)

PROTOCOL_VERSION = 1
BLOB_MAGIC = b"ENGR"

# [SPEC §G.1.3] Bố cục tiêu đề. provider_sig ĐÃ BỎ so với bản trước — nó thừa,
# vì trường signer của Celestia làm đúng việc đó và được đồng thuận bảo đảm.
# Tiết kiệm 65 byte mà KHÔNG đổi số share (vẫn 29), nên kinh tế DA giữ nguyên.
HEADER_STRUCT = struct.Struct(
    "<"      # little-endian, không đệm
    "4s"     #  0..4    MAGIC "ENGR"
    "B"      #  4..5    version
    "B"      #  5..6    kind
    "Q"      #  6..14   deadline (chỉ số tuyệt đối)
    "I"      # 14..18   shard
    "20s"    # 18..38   provider_id
    "32s"    # 38..70   deal_id
    "I"      # 70..74   payload_len
)
HEADER_SIZE = HEADER_STRUCT.size  # 74


# ═══════════════════════════════════════════════════════════════════════════
# 1. NAMESPACE  ·  [SPEC §G.1.2]
# ═══════════════════════════════════════════════════════════════════════════


def build_namespace(kind: BlobKind, chain_id: int, shard: int) -> bytes:
    """Dựng namespace Celestia v0 đầy đủ 29 byte cho một mảnh.

    [SPEC §G.1.2] Namespace v0 = 1 byte version + 18 byte 0 + 10 byte tự do.
    Engram dùng hết 10 byte tự do, không thừa byte nào:

        offset  len  trường
             0    1  PROTOCOL_VERSION
             1    1  kind        01 bundle · 02 ChildProof · 03 quyết toán · 04 sổ
             2    4  chain_id    của EVM quyết toán
             6    4  shard       (0 với kind != 01)

    MỖI MẢNH MỘT NAMESPACE là quyết định chống spam quan trọng nhất ở tầng này:
    worker chỉ tải dữ liệu namespace của mảnh mình, nên rác đổ vào mảnh khác
    KHÔNG TỐN MỘT BYTE BĂNG THÔNG NÀO của nó.

    Kẻ xấu muốn hạ tỉ lệ phủ xuống θ phải lấp θ·S_ns namespace, nên chi phí tấn
    công tỉ lệ THUẬN với S_ns, còn chi phí phòng thủ KHÔNG ĐỔI. Đây là chỗ hiếm
    hoi tăng một tham số chỉ có lợi.
    """
    free = struct.pack("<BBII", PROTOCOL_VERSION, int(kind), chain_id, shard)
    assert len(free) == NAMESPACE_ID_FREE_BYTES, "10 byte tự do phải dùng hết"
    # version byte 0 + 18 byte 0 dẫn đầu + 10 byte tự do = 29
    return bytes([0]) + bytes(18) + free


# ═══════════════════════════════════════════════════════════════════════════
# 2. TIÊU ĐỀ BLOB  ·  [SPEC §G.1.3]
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BlobHeader:
    """Tiêu đề 74 byte, PHẢI lọt trong share đầu tiên.

    [SPEC §G.1.3] Nếu tiêu đề không lọt vào share đầu thì worker buộc phải ráp
    lại CẢ blob mới biết có nên vứt hay không — tức là kẻ tấn công ép được worker
    làm việc chỉ bằng cách gửi blob dài. Share v1 chừa 458 byte, tiêu đề 74 byte,
    dư 384 byte. An toàn.
    """

    kind: BlobKind
    deadline: int
    shard: int
    provider_id: bytes  # 20 B
    deal_id: bytes  # 32 B
    payload_len: int
    version: int = PROTOCOL_VERSION

    def pack(self) -> bytes:
        return HEADER_STRUCT.pack(
            BLOB_MAGIC,
            self.version,
            int(self.kind),
            self.deadline,
            self.shard,
            self.provider_id.rjust(20, b"\0")[:20],
            self.deal_id.rjust(32, b"\0")[:32],
            self.payload_len,
        )

    @classmethod
    def unpack(cls, raw: bytes) -> "BlobHeader | None":
        """Trả None nếu không phân tích được. KHÔNG ném ngoại lệ — dữ liệu đến
        từ bên không tin được, và ngoại lệ trên đường nóng là một kiểu DoS."""
        if len(raw) < HEADER_SIZE:
            return None
        try:
            magic, ver, kind, deadline, shard, prov, deal, plen = HEADER_STRUCT.unpack(
                raw[:HEADER_SIZE]
            )
        except struct.error:
            return None
        if magic != BLOB_MAGIC:
            return None
        try:
            kind_enum = BlobKind(kind)
        except ValueError:
            return None
        return cls(kind_enum, deadline, shard, prov, deal, plen, ver)

    @property
    def key(self) -> tuple[bytes, bytes]:
        """[SPEC §E.4.2] Khoá sắp xếp (provider_id, deal_id).

        Guest yêu cầu khoá TĂNG NGHIÊM NGẶT, nên khử trùng lặp là miễn phí — một
        phép so sánh mỗi bước, không cần quy tắc chọn riêng."""
        return (self.provider_id, self.deal_id)


# ═══════════════════════════════════════════════════════════════════════════
# 3. BLOB ĐÃ Ở TRÊN DA
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ObservedBlob:
    """Một blob worker đọc được từ Celestia.

    `signer` KHÔNG do Engram đặt và KHÔNG do người đăng tự khai — nó nằm trong
    share phiên bản 1 và được đồng thuận Celestia xác minh khi nhận blob. Đây là
    lý do trường này đáng tin còn `header.provider_id` thì không.
    """

    height: int  # chiều cao block Celestia
    index: int  # chỉ số share trong block
    signer: bytes  # 20 B — [ext] Celestia SignerSize, ĐỒNG THUẬN ÁP ĐẶT
    header: BlobHeader | None
    payload: bytes

    @property
    def position(self) -> tuple[int, int]:
        return (self.height, self.index)


# ═══════════════════════════════════════════════════════════════════════════
# 4. THANG LỌC  ·  [SPEC §G.1.4]
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class FilterStats:
    """Đếm số blob rụng ở từng bậc — để kịch bản tấn công đo được hiệu quả lọc."""

    seen: int = 0
    drop_f1_length: int = 0
    drop_f2_header: int = 0
    drop_f3_key: int = 0
    drop_signer: int = 0
    kept: int = 0


def filter_blobs(
    blobs: list[ObservedBlob],
    *,
    expected_keys: set[tuple[bytes, bytes]],
    signer_of: dict[bytes, bytes],
    deadline: int,
    shard: int,
    max_payload: int,
) -> tuple[dict[tuple[bytes, bytes], ObservedBlob], FilterStats]:
    """[SPEC §G.1.4] Thang lọc, chạy NGOÀI mạch trên CPU của host.

    Thứ tự các bậc là BẮT BUỘC, không phải tuỳ tiện:

        F1  độ dài payload trong khoảng           so sánh, ~ns
        F2  MAGIC/version/kind/deadline/shard     so sánh hằng, ~ns
        F3  (provider_id, deal_id) ∈ tập kỳ vọng  tra bảng băm, ~100ns
        F3b LỌC THEO NGƯỜI KÝ  ← §J.2.1          so sánh 20 byte, ~50ns
        F6  xác minh Spartan trong guest          11,255e9 chu kỳ

    ĐẶT F6 TRƯỚC F3 LÀ THẢM HOẠ: mỗi blob rác sẽ tốn 11,255e9 chu kỳ, và kẻ tấn
    công trả 0,00009 $ để đốt hàng phút zkVM. Đó là lý do guest lặp trên DANH
    SÁCH KỲ VỌNG chứ không lặp trên thứ tải về (§E.4.2).

    ĐỊNH LÝ CHỐNG SPAM [SPEC §G.1.4]: chi phí sau F3 là hàm của N — số hợp đồng
    trong ảnh chụp — chứ không phải hàm của lượng dữ liệu trên namespace. Chi phí
    trước F3 bị chặn trên bởi trần block Celestia.

    [CHỐT — C1-b] Chỉ hiện thực bản ĐÃ SỬA. Lỗ hổng được mô tả trong comment
    chứ không hiện thực thành mã, để không ai vô tình bật nhầm.
    """
    stats = FilterStats()
    best: dict[tuple[bytes, bytes], ObservedBlob] = {}

    for blob in blobs:
        stats.seen += 1

        # ── F1 ── độ dài
        if not (0 < len(blob.payload) <= max_payload):
            stats.drop_f1_length += 1
            continue

        # ── F2 ── tiêu đề khớp ảnh chụp
        h = blob.header
        if h is None or h.version != PROTOCOL_VERSION:
            stats.drop_f2_header += 1
            continue
        if h.kind is not BlobKind.BUNDLE or h.deadline != deadline or h.shard != shard:
            stats.drop_f2_header += 1
            continue
        if h.payload_len != len(blob.payload):
            stats.drop_f2_header += 1
            continue

        # ── F3 ── khoá phải nằm trong tập kỳ vọng, lấy từ ảnh chụp đã đóng băng
        key = h.key
        if key not in expected_keys:
            stats.drop_f3_key += 1
            continue

        # ── F3b ── NGƯỜI KÝ  [SPEC §J.2.1]
        #
        # Kẻ ngoài forge được mọi byte trong tiêu đề, kể cả provider_id. Thứ nó
        # KHÔNG forge được là trường signer, vì đồng thuận Celestia kiểm nó phải
        # trùng người ký giao dịch, và nó không có khoá riêng của nút.
        registered = signer_of.get(h.provider_id)
        if registered is None or blob.signer != registered:
            stats.drop_signer += 1
            continue

        # ── F4 ── mỗi khoá giữ MỘT blob.
        # Sau F3b thì mọi blob còn lại đều do chính nút đăng, nên chọn cái nào
        # cũng an toàn. Lấy sớm nhất theo (chiều cao, chỉ số) cho tất định.
        prev = best.get(key)
        if prev is None or blob.position < prev.position:
            best[key] = blob

    stats.kept = len(best)
    return best, stats


# ═══════════════════════════════════════════════════════════════════════════
# 5. CHI PHÍ DA  ·  [SPEC §G.1.3]
# ═══════════════════════════════════════════════════════════════════════════


def shares_for(payload_bytes: int) -> int:
    """Số share Celestia cần cho một blob, dùng bố cục share v1.

    Share đầu chứa 458 byte (đã trừ 20 byte signer), share tiếp theo 482 byte.
    Bundle 13.776 + tiêu đề 74 = 13.850 → 458 + 28×482 = 13.954 ≥ 13.850 → 29 share.
    """
    if payload_bytes <= FIRST_SHARE_PAYLOAD_V1:
        return 1
    remain = payload_bytes - FIRST_SHARE_PAYLOAD_V1
    return 1 + (remain + CONT_SHARE_PAYLOAD - 1) // CONT_SHARE_PAYLOAD


def pfb_gas(payload_bytes: int) -> int:
    """[SPEC §G.1.3] gas = phí cố định + số share × 512 × 8."""
    return CELESTIA_PFB_FIXED_GAS + shares_for(payload_bytes) * SHARE_SIZE * CELESTIA_GAS_PER_BLOB_BYTE


def pfb_fee_utia(payload_bytes: int) -> float:
    return pfb_gas(payload_bytes) * CELESTIA_MIN_GAS_PRICE_UTIA


def pfb_fee_usd(payload_bytes: int, tia_price_usd: float = 0.65) -> float:
    """Bundle 13.850 B → 29 share → 183.784 gas → 367,6 utia → 0,00024 $."""
    return pfb_fee_utia(payload_bytes) * 1e-6 * tia_price_usd


assert SIGNER_SIZE == 20, "[ext] Celestia SignerSize phải là 20 byte"
assert FIRST_SHARE_PAYLOAD_V1 == 458, "bố cục share v1 sai"
assert HEADER_SIZE == 74, "tiêu đề phải là 74 byte sau khi bỏ provider_sig"
