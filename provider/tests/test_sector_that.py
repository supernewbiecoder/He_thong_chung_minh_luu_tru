"""Sector phải là BYTE THẬT trên đĩa, không phải cờ trong bộ nhớ.

Bản trước sinh nội dung chunk từ một hạt giống và mô phỏng mất dữ liệu bằng một
tập chỉ số. Cách đó cho `sealed_root` và đường Merkle đều thật, nhưng đánh mất
đúng thứ cả hệ tồn tại để kiểm: không có byte nào để xoá, nên "nút gian bị bắt"
chỉ là kết luận về một cờ.
"""

import sys, pathlib, tempfile

for m in ("common", "provider"):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / m / "src"))

import pytest

from provider.sector import ChunkMissing, Sector
from provider.sealing import derive_replica_id, seal
from provider.storage import DealStorage

DEAL = b"\xab" * 32
RID = derive_replica_id(b"\x01" * 20, DEAL, b"\x02" * 32, b"\x03" * 32)


@pytest.fixture
def root():
    return pathlib.Path(tempfile.mkdtemp(prefix="engram-test-"))


def test_sector_chiem_dung_luong_that(root):
    sec = Sector.create(root, DEAL, 8)
    assert sec.on_disk_bytes == 8 * 4096
    assert sec.path.exists()


def test_doc_chunk_la_mot_phep_seek(root):
    sec = Sector.create(root, DEAL, 8)
    assert len(sec.chunk(5)) == 4096
    assert sec.chunk(5) != sec.chunk(4)


def test_xoa_sector_thi_doc_nem_loi_khong_tra_rac(root):
    """Nút đã xoá thật thì KHÔNG CÓ GÌ để trả. Trả rác mô tả sai tình huống —
    đó là nút còn dữ liệu nhưng dữ liệu hỏng."""
    sec = Sector.create(root, DEAL, 8)
    sec.delete()
    assert sec.on_disk_bytes == 0
    with pytest.raises(ChunkMissing):
        sec.chunk(0)


def test_duc_lo_doi_byte_tren_dia(root):
    sec = Sector.create(root, DEAL, 8)
    truoc = sec.chunk(0)
    sec.lose_chunks([0])
    assert sec.chunk(0) == b"\x00" * 4096 != truoc


def test_mat_du_lieu_LAM_DOI_vet_niem_phong(root):
    """Đây là bài kiểm quan trọng nhất: vết phải đổi vì BYTE đổi, không phải vì
    một cờ được bật."""
    st = DealStorage.create(root, DEAL, 8)
    truoc = seal(list(st.iter_chunks()), RID).sealed_root
    st.lose_fraction(0.5)
    sau = seal(list(st.iter_chunks()), RID).sealed_root
    assert sau != truoc


def test_seal_doc_theo_luong_khong_nap_ca_sector(root):
    st = DealStorage.create(root, DEAL, 8)
    assert sum(1 for _ in st.iter_chunks()) == 8


def test_vet_niem_phong_chiem_1_6_phan_tram(root):
    st = DealStorage.create(root, DEAL, 100)
    assert st.seal_form_bytes / st.raw_bytes == pytest.approx(64 / 4096)
