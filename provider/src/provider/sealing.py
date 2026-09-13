"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §E.1] Niêm phong — Thuật toán 1c, KHỚP VỚI MẠCH
═══════════════════════════════════════════════════════════════════════════════

 `seal()` hiện thực ĐÚNG thuật toán mà mạch Nova/Spartan trong `circuit/` kiểm:

     D_i = fold limb của chunk           acc₀ = Fr(chunk_size); accₖ₊₁ = H2(accₖ, limbₖ)
     R_i = H4(D_i, S_{i-1}, i, replica_id)
     S_i = H2(S_{i-1}, R_i)

 Đối chiếu: `circuit/prover/src/sealing.rs` dòng 102-106, và ràng buộc tương ứng
 trong `circuit/prover/src/proving.rs` phần 5b.

 ── VÌ SAO ĐỔI VỀ 1c, VÀ MẤT GÌ ─────────────────────────────────────────────

 Bản trước hiện thực SeqWide (Thuật toán 1d) có fan-in φ=6. Nhưng MẠCH thì
 không, nên repo chứa hai thuật toán mâu thuẫn nhau: số liệu L1 đo từ mạch 1c
 trong khi mã Python mô tả 1d.

 Chọn cho Python theo mạch, vì mạch là thứ chạy thật và sinh ra số đo. Sealing
 không phải đóng góp chính của bài — bài tự nói phần này orthogonal.

 MẤT GÌ, phải ghi rõ chứ không giấu:

 ① Điểm mốc lại hoạt động. Không có fan-in, kẻ gian lưu S mỗi 1.000 chunk —
    hết 268 KB — rồi nối chuỗi từ mắt gần nhất trong 0,04 GIÂY. Độ sâu tuần tự
    dài bao nhiêu cũng vô nghĩa nếu nối được từ giữa.

 ② Phần hấp thụ chunk TÁCH khỏi chuỗi. `D_i` chỉ phụ thuộc chunk i, nên phần
    lớn công việc song song hoá được. Đo trong bài: 97,8 % song song hoá được,
    nút thật 12 nhân mất 23 phút còn kẻ gian song song hoá mất 4,92 phút.

 Hai điều trên nghĩa là **sàn kẻ gian của 1c thấp hơn hẳn 1d**, và mọi con số
 `t_regen` suy từ giả định có fan-in KHÔNG áp dụng cho mạch hiện tại.

 ── PHÂN TÍCH SEQWIDE VẪN GIỮ ───────────────────────────────────────────────

 `seal_seqwide()` và `fanin_positions()` giữ nguyên, và bộ test bao đóng vẫn
 chạy. Chúng là PHÂN TÍCH một thiết kế thay thế, không phải đường chạy chính.
 Bài nên trình bày đúng như vậy: SeqWide là hướng thiết kế, mạch hiện thực 1c.

 ── [CHỐT D3] MÔ HÌNH CHI PHÍ ────────────────────────────────────────────────

 Tầng Python không chạy Poseidon2 thật; thời gian TÍNH bằng `costs.seal_seconds()`
 từ số đo 11,89 µs mỗi hoán vị. Mạch Rust thì dùng Poseidon2 THẬT — xem
 `circuit/core_primitives/src/poseidon2.rs`.
═══════════════════════════════════════════════════════════════════════════════
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


def _fold_limbs(chunk: bytes, chunk_size: int, rate: int = 31) -> bytes:
    """D_i — gấp limb của chunk. Khớp `core_primitives::chunking::fold_limbs()`:

        acc₀   = Fr(chunk_size_bytes)
        accₖ₊₁ = H2(accₖ, limbₖ)

    Mạch tái tính đúng vòng lặp này từ 133 limb thô, nên nút giữ mỗi digest 32
    byte KHÔNG dựng được limb hợp lệ — buộc phải giữ dữ liệu thật.
    """
    acc = poseidon2_stub(chunk_size.to_bytes(8, "little"))
    for off in range(0, len(chunk), rate):
        acc = poseidon2_stub(acc, chunk[off : off + rate])
    return acc


def seal(chunks: list[bytes], replica_id: bytes, rate: int = SEAL_RATE) -> SealResult:
    """Thuật toán 1c — KHỚP VỚI MẠCH trong `circuit/`.

        D_i = fold limb chunk
        R_i = H4(D_i, S_{i-1}, i, replica_id)
        S_i = H2(S_{i-1}, R_i)

    KHÔNG có fan-in, và KHÔNG có tham số `threads`. Nhưng lý do không có
    `threads` ở đây KHÁC với bản SeqWide: chuỗi S vẫn tuần tự, song phần `D_i`
    thì tách rời và song song hoá được. Xem docstring đầu mô-đun, mục ②.
    """
    n = len(chunks)
    s_chain: list[bytes] = []
    r_values: list[bytes] = []
    leaves: list[bytes] = []
    s_prev = replica_id
    chunk_size = len(chunks[0]) if chunks else 0

    for i, chunk in enumerate(chunks):
        d_i = _fold_limbs(chunk, chunk_size)
        # H4(a,b,c,d) = H2(H2(a,b), H2(c,d)) — đúng `poseidon2_hash_4` bên Rust
        r_i = poseidon2_stub(
            poseidon2_stub(d_i, s_prev),
            poseidon2_stub(i.to_bytes(8, "little"), replica_id),
        )
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


def seal_seqwide(chunks: list[bytes], replica_id: bytes,
                 rate: int = SEAL_RATE) -> SealResult:
    """Thuật toán 1d — SeqWide, có fan-in φ=6. THIẾT KẾ THAY THẾ, không phải
    đường chạy chính.

    Giữ lại vì phần phân tích bao đóng fan-in vẫn có giá trị, và vì nếu sau này
    đưa fan-in vào mạch thì đây là bản tham chiếu. Mạch hiện tại KHÔNG hiện
    thực hàm này — đừng dùng nó để sinh số liệu cho bài.

    Ba thay đổi so với 1c, và cả ba phải đi cùng nhau:

      ① GIEO trạng thái bằng S_{i-1} — chuyển việc băm chunk từ CẠNH chuỗi sang
         TRÊN chuỗi, để thêm nhân CPU không rút ngắn được gì.
      ② FAN-IN φ=6 — làm điểm mốc mất tác dụng.
      ③ RATE điều chỉnh được — nút chỉnh độ dài chuỗi.
    """
    n = len(chunks)
    s_chain: list[bytes] = []
    r_values: list[bytes] = []
    leaves: list[bytes] = []
    s_prev = replica_id

    for i, chunk in enumerate(chunks):
        seed_parts = [s_prev]
        for pos in fanin_positions(i, replica_id):
            seed_parts.append(s_chain[pos])
        seed_parts += [i.to_bytes(8, "little"), replica_id]
        st = poseidon2_stub(*seed_parts)

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
