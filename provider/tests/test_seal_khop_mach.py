"""`seal()` phía Python phải hiện thực ĐÚNG thuật toán mà mạch Rust kiểm.

Trước đây Python hiện thực SeqWide (1d, có fan-in) còn mạch hiện thực 1c (không
fan-in). Repo vì thế chứa hai thuật toán mâu thuẫn nhau: số liệu L1 đo từ mạch
1c trong khi mã Python mô tả 1d.

Đối chiếu: circuit/prover/src/sealing.rs dòng 102-106
    let d_i = chunk_to_fr(&chunk_buf);
    let r_i = poseidon2_hash_4(d_i, s_prev, Fr::from(i), replica_id);
    let s_i = hash_2(s_prev, r_i);
"""

import sys, pathlib, inspect

for m in ("common", "provider"):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / m / "src"))

from engram_common.crypto import poseidon2_stub
from provider.sealing import _fold_limbs, seal, seal_seqwide

RID = b"\xaa" * 32
CHUNKS = [bytes([i % 251]) * 4096 for i in range(4)]


def test_seal_khop_cong_thuc_cua_mach():
    """Tính tay theo đúng công thức Rust, phải ra cùng chuỗi."""
    res = seal(CHUNKS, RID)
    s_prev = RID
    for i, chunk in enumerate(CHUNKS):
        d_i = _fold_limbs(chunk, 4096)
        r_i = poseidon2_stub(
            poseidon2_stub(d_i, s_prev),
            poseidon2_stub(i.to_bytes(8, "little"), RID),
        )
        s_i = poseidon2_stub(s_prev, r_i)
        assert res.r_values[i] == r_i
        assert res.s_chain[i] == s_i
        s_prev = s_i


def test_seal_khong_con_fan_in():
    """Chốt bằng mã nguồn: `seal` không gọi `fanin_positions` nữa."""
    assert "fanin_positions" not in inspect.getsource(seal)


def test_seqwide_van_con_nhung_la_duong_khac():
    """Giữ để phân tích bao đóng, nhưng KHÁC kết quả — nên không lẫn được."""
    assert "fanin_positions" in inspect.getsource(seal_seqwide)
    assert seal(CHUNKS, RID).sealed_root != seal_seqwide(CHUNKS, RID).sealed_root


def test_doi_mot_byte_thi_doi_vet():
    khac = [CHUNKS[0][:-1] + b"\xff"] + CHUNKS[1:]
    assert seal(khac, RID).sealed_root != seal(CHUNKS, RID).sealed_root


def test_doi_replica_id_thi_doi_vet():
    assert seal(CHUNKS, b"\xbb" * 32).sealed_root != seal(CHUNKS, RID).sealed_root


def test_fold_limbs_bat_dau_tu_chunk_size():
    """acc₀ = Fr(chunk_size_bytes), ép hằng số — prover không chọn giá trị khác."""
    assert _fold_limbs(b"", 4096) == poseidon2_stub((4096).to_bytes(8, "little"))
