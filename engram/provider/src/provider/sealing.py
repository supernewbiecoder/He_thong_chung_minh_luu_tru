"""
[SPEC §E.1.4] Thuật toán 1d — SeqWide.

 ── BA THAY ĐỔI SO VỚI THUẬT TOÁN 1, VÀ CẢ BA PHẢI ĐI CÙNG NHAU ──────────

 ① GIEO trạng thái bằng S_{i-1}
    Chuyển toàn bộ việc băm chunk từ CẠNH chuỗi sang TRÊN chuỗi. Đây là điều
    kiện để thêm nhân CPU không rút ngắn được gì.

    Không có nó: d_i = toFr(chunk_i) chỉ phụ thuộc chunk i, nên 133 trong 137
    phép băm — 97,8 % — song song hoá được. Nút thật 12 nhân mất 23 phút, kẻ
    gian song song hoá mất 4,92 phút. KẺ GIAN NHANH HƠN NÚT THẬT 4,7 LẦN.

 ② FAN-IN φ = 6
    Làm ĐIỂM MỐC vô dụng. Không có nó, kẻ gian lưu S mỗi 1.000 chunk — hết
    268 KB — rồi nối lại chuỗi từ mắt gần nhất trong 0,04 GIÂY. Độ sâu tuần tự
    dài bao nhiêu cũng vô nghĩa nếu nối được từ giữa.

    Với φ=6, tính lại r_j cần 6 giá trị S, mỗi giá trị lại cần 6 giá trị nữa;
    chỉ 9 tầng là bao đóng phủ hết 8,4 triệu vị trí. Dựng lại MỘT vị trí =
    dựng lại CẢ sector.

 ③ RATE = 4
    Nút điều chỉnh độ dài. Chọn 4 để sàn kẻ gian vượt 30 phút.

 ── [CHỐT D3] MÔ HÌNH CHI PHÍ ────────────────────────────────────────────

 Không chạy Poseidon2 thật. Cấu trúc cây, chỉ số, và mọi kích thước là THẬT;
 thời gian được TÍNH bằng costs.seal_seconds() từ số đo 11,89 µs mỗi hoán vị.
"""

from __future__ import annotations

from dataclasses import dataclass

from engram_common.constants import SEAL_FANIN_PHI, SEAL_RATE
from engram_common.costs import seal_seconds
from engram_common.crypto import keccak, merkle_root, poseidon2_stub


def fanin_positions(i: int, replica_id: bytes = b"", phi: int = SEAL_FANIN_PHI) -> list[int]:
    """π_1(i) … π_{φ-1}(i) — các vị trí TRƯỚC i mà r_i phụ thuộc vào.

    ── MỘT CÁI BẪY SỐ HỌC ĐÃ TỪNG DÍNH ──────────────────────────────────────

    Công thức đầu tiên tôi viết là `(i * a + b) % i`. Nó SAI, và sai im lặng:
    `i * a % i == 0` với mọi a, nên kết quả luôn bằng `b % i` — cùng MỘT vị trí
    cho mọi t. Fan-in thoái hoá về bậc 1, bao đóng phụ thuộc không lan ra, và
    điểm mốc lại hoạt động như chưa có fan-in.

    Đây đúng là loại lỗi mà fan-in tồn tại để chống, nên nó phải có test riêng
    kiểm bao đóng thật sự lan — xem tests/test_fanin_closure.py.

    Cách đúng: dẫn xuất bằng BĂM, và trộn replica_id để hai bản sao khác nhau
    có đồ thị phụ thuộc khác nhau.
    """
    if i == 0:
        return []
    out: list[int] = []
    for t in range(phi - 1):
        h = poseidon2_stub(replica_id, i.to_bytes(8, "little"), t.to_bytes(2, "little"))
        out.append(int.from_bytes(h[:8], "little") % i)
    return out


@dataclass
class SealResult:
    sealed_root: bytes
    s_chain: list[bytes]      # {S_i} — nút PHẢI giữ, 32 B mỗi chunk
    r_values: list[bytes]     # {R_i} — nút PHẢI giữ, 32 B mỗi chunk
    seconds_modelled: float   # thời gian THẬT sẽ tốn nếu chạy Poseidon2 thật


def seal(chunks: list[bytes], replica_id: bytes, rate: int = SEAL_RATE) -> SealResult:
    """Thuật toán 1d. Trả về cây niêm phong và thời gian mô hình hoá.

    KHÔNG có tham số `threads`. Đó không phải thiếu sót — Thuật toán 1d có 0 %
    công việc song song hoá được. Máy 64 nhân niêm phong MỘT sector không nhanh
    hơn máy 1 nhân.

    Nhiều nhân vẫn hữu ích theo chiều khác: seal NHIỀU SECTOR cùng lúc, mỗi
    nhân một sector. Đó là cách Filecoin vận hành, và là lý do onboard 100 TB
    mất 2,7 ngày trên máy 64 nhân thay vì 171 ngày tuần tự.
    """
    n = len(chunks)
    s_chain: list[bytes] = []
    r_values: list[bytes] = []
    leaves: list[bytes] = []
    s_prev = replica_id

    for i, chunk in enumerate(chunks):
        # ① gieo trạng thái bằng mắt trước + fan-in ── TUẦN TỰ
        seed_parts = [s_prev]
        for pos in fanin_positions(i, replica_id):
            seed_parts.append(s_chain[pos])
        seed_parts += [i.to_bytes(8, "little"), replica_id]
        st = poseidon2_stub(*seed_parts)

        # ② hấp thụ limb của chunk ── NẰM TRÊN chuỗi, không tách ra được
        for off in range(0, len(chunk), 31 * rate):
            st = poseidon2_stub(st, chunk[off : off + 31 * rate])

        r_i = st
        s_i = poseidon2_stub(s_prev, r_i)
        r_values.append(r_i)
        s_chain.append(s_i)
        leaves.append(poseidon2_stub(r_i, s_i))
        s_prev = s_i

    return SealResult(
        sealed_root=merkle_root(leaves, hasher=poseidon2_stub),
        s_chain=s_chain,
        r_values=r_values,
        seconds_modelled=seal_seconds(n),
    )


def derive_replica_id(
    provider_id: bytes, deal_id: bytes, piece_root: bytes, activation_beacon: bytes
) -> bytes:
    """[SPEC §D.1.4] replica_id — DẪN XUẤT, nút không tự chọn được.

    Mỗi thành phần chặn một tấn công cụ thể:

      provider_id        nút A lấy bundle nút B công bố trên DA rồi nộp lại
      deal_id            MỘT lần niêm phong dùng cho 100 hợp đồng — nút giữ 1
                         phần dữ liệu, thu tiền 100 phần
      piece_root         nút niêm phong 32 GiB số 0 thay vì dữ liệu khách
      activation_beacon  niêm phong trước khi có hợp đồng · lập lại hợp đồng cũ
                         và dùng lại nguyên bản niêm phong đã lộ

    Guest tính lại giá trị này và đối chiếu, nên nút không bịa được.
    """
    return keccak(b"ENGRAM_REPLICA_V1", provider_id, deal_id, piece_root, activation_beacon)
