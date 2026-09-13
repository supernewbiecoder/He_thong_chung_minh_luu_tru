"""[R7] Tham số lịch của hợp đồng phải khớp hồ sơ mà guest dùng.

Bản trước hợp đồng ghim cứng `DEADLINES_PER_EPOCH = 48` và `shardCount = 10`,
tức ghim hồ sơ production. Chạy mô phỏng với PROFILE_SIM (D = 4) thì
`deadlineIdx` hợp đồng dẫn xuất nằm trong [0,48) còn guest chỉ xét [0,4), nên
phần lớn hợp đồng rơi vào deadline không ô nào phủ.

Chưa lộ ra vì luồng Python không gọi `openDeal` của Solidity. Nối thật là vỡ.
Giờ hai giá trị đó nằm trong constructor, và bài kiểm này chốt rằng mọi hồ sơ
đều truyền được.
"""

import re, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from engram_common.constants import PROFILE_PRODUCTION, PROFILE_SIM

SOL = (pathlib.Path(__file__).resolve().parents[2]
       / "chain" / "src" / "EngramManager.sol").read_text(encoding="utf-8")


def test_hop_dong_khong_con_ghim_cung_so_deadline():
    assert "uint64 public immutable DEADLINES_PER_EPOCH;" in SOL
    assert "uint64 public constant DEADLINES_PER_EPOCH = 48;" not in SOL


def test_shardCount_la_immutable_khong_phai_bien_khong_setter():
    assert "uint32 public immutable shardCount;" in SOL
    assert "uint32 public shardCount = 10;" not in SOL


def test_constructor_nhan_ca_hai_tham_so():
    assert "uint64 _deadlinesPerEpoch" in SOL and "uint32 _shardCount" in SOL


def test_ca_hai_ho_so_deu_truyen_duoc():
    for prof in (PROFILE_PRODUCTION, PROFILE_SIM):
        assert prof.deadlines_per_epoch > 0
        assert prof.deadlines_per_epoch < 2**64
