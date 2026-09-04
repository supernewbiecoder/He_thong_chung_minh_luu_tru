"""
═══════════════════════════════════════════════════════════════════════════════
 [SPEC §K.1]  Bảng tham số  ·  [SPEC §A.7]  Bảng ký hiệu
═══════════════════════════════════════════════════════════════════════════════

 Mọi hằng số của giao thức nằm ở đúng một chỗ: tệp này. Tên biến trùng ký hiệu
 trong §A.7 để tra ngược được.

 Nhãn dùng trong tệp:
   [CHỐT]  đã quyết trong thiết kế, không đổi tuỳ tiện
   [ĐO]    có số đo thật, kèm nguồn
   [ext]   lấy từ tài liệu bên ngoài (Celestia / Filecoin), nguồn ở §M.2.4
   [MỞ]    CHƯA quyết — đọc ghi chú trước khi dựa vào
   [KHÔNG MÔ PHỎNG]  nằm ngoài phạm vi bản hiện thực này
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ═══════════════════════════════════════════════════════════════════════════
# 1. NGUYÊN HÀM  ·  [SPEC §2 / §A.5.4]
# ═══════════════════════════════════════════════════════════════════════════

CHUNK_SIZE_BYTES = 4096
"""[CHỐT] Đơn vị nhỏ nhất được thách thức."""

LIMB_SIZE_BYTES = 31
"""[SPEC §A.5.4] 31 chứ không phải 32: phần tử trường BN254 có p ≈ 2^254, nên
32 byte có thể tràn. 31 byte thì chắc chắn < p, ánh xạ là đơn ánh."""

LIMBS_PER_CHUNK = 133
"""[ĐO] ceil(4096 / 31) = 133. Test của repo gốc khẳng định num_limbs(4096)==133.
Con số 133 xuất hiện khắp đặc tả đều bắt nguồn từ đây."""

# ═══════════════════════════════════════════════════════════════════════════
# 2. NIÊM PHONG — Thuật toán 1d SeqWide  ·  [SPEC §E.1.4]
# ═══════════════════════════════════════════════════════════════════════════

SEAL_RATE = 4
"""[CHỐT] Số limb hấp thụ mỗi lần hoán vị Poseidon2 t=8.
Đây là NÚT ĐIỀU CHỈNH ĐỘ DÀI: rate thấp → nhiều lần hoán vị mỗi chunk → chuỗi
tuần tự dài hơn → sàn kẻ gian cao hơn, nhưng nút thật cũng chậm hơn.
  rate 7 → 20 hoán vị/chunk → sàn 22,1 phút
  rate 4 → 35 hoán vị/chunk → sàn 38,4 phút   ← đã chốt
  rate 1 → 134 hoán vị/chunk → sàn 2,38 giờ"""

SEAL_FANIN_PHI = 6
"""[CHỐT] Bậc fan-in φ. Ký hiệu là φ chứ không phải d, vì d là chỉ số deadline.

VÌ SAO BẮT BUỘC: không có fan-in, r_i chỉ phụ thuộc mắt liền trước, nên kẻ gian
lưu S mỗi 1.000 chunk (268 KB) rồi nối lại chuỗi từ giữa trong 0,04 GIÂY. Độ sâu
tuần tự dài bao nhiêu cũng vô nghĩa. Với φ=6, chỉ 9 tầng phụ thuộc là bao đóng
phủ hết 8,4 triệu vị trí, nên dựng lại MỘT vị trí = dựng lại CẢ sector."""

SEAL_K_DELAY = 1
"""[CHỐT] Số lần lặp băm thêm trên chuỗi. =1 nghĩa là không thêm trễ; rate=4 đã
đủ đạt sàn 38,4 phút."""

@dataclass(frozen=True)
class SectorProfile:
    """[CHỐT E1] Kích thước sector khi mô phỏng.

    Sector thật 32 GiB = 8.388.608 chunk. Với 20 hợp đồng là 640 GiB — không mô
    phỏng nổi, và niêm phong thật mất 1,26 giờ MỖI hợp đồng.

    Bản mô phỏng dùng sector nhỏ, nhưng MỌI TÍNH CHẤT CẤU TRÚC vẫn thật:
    piece_root, sealed_root, chỉ số thách thức, đường Merkle, đồ thị fan-in.
    Chỉ có KÍCH THƯỚC là nhỏ đi, và thời gian được tính bằng mô hình chi phí quy
    chiếu về sector thật.
    """

    name: str
    chunks: int

    @property
    def bytes_(self) -> int:
        return self.chunks * CHUNK_SIZE_BYTES

    @property
    def tree_height(self) -> int:
        return self.chunks.bit_length() - 1

    @property
    def seal_form_bytes(self) -> int:
        """{R,S} = 64 byte mỗi chunk = 1,6 % dữ liệu."""
        return self.chunks * 64


SECTOR_TINY = SectorProfile("tiny", 1_024)          # 4 MiB   · cây cao 10
SECTOR_SMALL = SectorProfile("small", 16_384)       # 64 MiB  · cây cao 14
SECTOR_MEDIUM = SectorProfile("medium", 262_144)    # 1 GiB   · cây cao 18
SECTOR_PRODUCTION = SectorProfile("production", 8_388_608)  # 32 GiB · cây cao 23

SECTOR_PROFILES = {p.name: p for p in (SECTOR_TINY, SECTOR_SMALL, SECTOR_MEDIUM, SECTOR_PRODUCTION)}

CHUNKS_PER_SECTOR = SECTOR_PRODUCTION.chunks
"""[SPEC §A.6] 32 GiB / 4096 B. 'Sector' CHỈ là đơn vị đóng gói và quy chiếu
chi phí — KHÔNG phải đơn vị chứng minh. Đơn vị chứng minh là hợp đồng."""

SECTOR_TREE_HEIGHT = SECTOR_PRODUCTION.tree_height
"""23 — log2(8.388.608)."""

SEAL_FORM_OVERHEAD_RATIO = 0.016
"""[SPEC §E.1.1] {R_i, S_i} = 64 B mỗi chunk = 512 MiB cho một sector = 1,6 %."""

# ═══════════════════════════════════════════════════════════════════════════
# 3. THÁCH THỨC  ·  [SPEC §E.2.1 / §E.3.3]
# ═══════════════════════════════════════════════════════════════════════════

CHALLENGES_PER_DEADLINE_C = 16
"""[CHỐT] C — số thách thức mỗi deadline, rải đều.

TÍNH CHẤT RẢI ĐỀU: mỗi khoảng n/C có đúng một thách thức, nên xoá một khối liền
không né được."""

CHALLENGES_ACTIVATION_K_ACT = 20
"""[CHỐT] k_act — thách thức của bằng chứng kích hoạt, chạy MỘT LẦN cả đời hợp
đồng. Bắt 99,68 % nếu nút gian 1/4 dữ liệu.

Đổi tên từ 'k' vì trước đây k mang ba nghĩa khác nhau — xem §M.3.3."""

# ═══════════════════════════════════════════════════════════════════════════
# 4. THỜI GIAN  ·  [SPEC §F.1 / §F.2]
# ═══════════════════════════════════════════════════════════════════════════
#
# QUY TẮC VÀNG [SPEC §F.1.2]: KHÔNG một giá trị nào trong ảnh chụp, bundle, hay
# phán quyết được dẫn xuất từ đồng hồ cục bộ. Đồng hồ của hệ là CHIỀU CAO BLOCK
# CELESTIA. Trong toàn bộ mã này, `time.time()` chỉ được dùng cho log và hẹn giờ
# poll, không bao giờ cho logic giao thức.

CELESTIA_BLOCK_TIME_S = 6.0
"""[ext] Xấp xỉ. Chỉ dùng để quy đổi khi hiển thị, không dùng trong logic."""


@dataclass(frozen=True)
class TimingProfile:
    """[SPEC §F.2.1] Lịch thời gian. Hai hồ sơ: `sim` để demo, `production` để thật.

    [CHỐT — quyết định D1] Epoch thật dài 24 giờ nên không demo được: một epoch
    mất 24 giờ đồng hồ thật. Hồ sơ `sim` rút lịch lại nhưng VẪN dùng block
    Celestia thật, vẫn đúng kỷ luật chiều cao. Chỉ lịch ngắn lại.
    """

    name: str
    deadline_len_blocks: int  # L_d
    deadlines_per_epoch: int  # D
    submit_window_blocks: int  # W
    beacon_delay_blocks: int  # δ
    beacon_mix_blocks: int  # k_mix

    @property
    def epoch_len_blocks(self) -> int:
        return self.deadline_len_blocks * self.deadlines_per_epoch

    @property
    def epoch_len_seconds(self) -> float:
        return self.epoch_len_blocks * CELESTIA_BLOCK_TIME_S


PROFILE_SIM = TimingProfile(
    name="sim",
    deadline_len_blocks=10,   # ~1 phút
    deadlines_per_epoch=4,    # epoch ~4 phút
    submit_window_blocks=6,   # ~36 giây, đủ cho vài blob vào block
    beacon_delay_blocks=2,
    beacon_mix_blocks=4,
)
"""[CHỐT — quyết định A1-b] Hồ sơ demo. Epoch ~4 phút thay vì 24 giờ.

Vì sao không ngắn hơn: cửa sổ nộp phải đủ dài để blob thật sự vào được block
Celestia. W=6 block ≈ 36 giây. Ngắn hơn nữa (W=3) thì blob có thể lỡ nhịp và
sinh ABSENT GIẢ — lỗi của lịch chứ không phải của nút, rất khó debug."""

PROFILE_PRODUCTION = TimingProfile(
    name="production",
    deadline_len_blocks=300,  # 30 phút
    deadlines_per_epoch=48,  # 24 giờ  [ext] giống hệt Filecoin
    submit_window_blocks=200,  # W = 20 phút
    beacon_delay_blocks=5,  # δ
    beacon_mix_blocks=4,  # k_mix
)
"""[CHỐT] Giá trị thật trong §K.1."""

# ═══════════════════════════════════════════════════════════════════════════
# 5. PHÂN MẢNH VÀ WORKER  ·  [SPEC §G.1.2 / §A.4.3 / §I.1.6]
# ═══════════════════════════════════════════════════════════════════════════

WORKER_REDUNDANCY_R = 2
"""[CHỐT] r — số worker phục vụ mỗi mảnh. Cả r đều chạy; hoà giải theo sức nặng
bằng cớ PASS ≻ FAIL ≻ NONE (§H.1.4)."""

NFR05_FIXED_COST_BUDGET = 20
"""[SPEC §I.1.6 NFR-05] Chọn D·S_ns ≤ N / 20 để chi phí cố định f ≤ 20 % tổng.

NGƯỢC TRỰC GIÁC: mạng NHỎ phải chia ÍT. Chia nhỏ ở mạng nhỏ nghĩa là trả f
nhiều lần cho những mảnh gần rỗng. Ở N=1.000 với D·S=768 thì f chiếm 75,6 %."""


def recommended_shard_count(n_deals: int, deadlines_per_epoch: int) -> int:
    """[SPEC §I.1.6] S_ns phải là tham số điều chỉnh theo N, không phải hằng số
    biên dịch. Trả về số mảnh lớn nhất còn thoả NFR-05, tối thiểu 1."""
    if n_deals <= 0:
        return 1
    budget = n_deals // NFR05_FIXED_COST_BUDGET
    return max(1, budget // max(1, deadlines_per_epoch))


# ═══════════════════════════════════════════════════════════════════════════
# 6. LỚP DA — CELESTIA  ·  [SPEC §G.1]
# ═══════════════════════════════════════════════════════════════════════════

SHARE_SIZE = 512
"""[ext] Celestia: SHARE_SIZE = 512 byte."""

NAMESPACE_SIZE = 29
"""[ext] NAMESPACE_VERSION_SIZE 1 + NAMESPACE_ID_SIZE 28."""

NAMESPACE_ID_FREE_BYTES = 10
"""[ext] Namespace v0 = 18 byte 0 dẫn đầu + 10 byte tự do. Engram dùng hết 10:
1 version + 1 kind + 4 chain_id + 4 shard (xem blob.py)."""

SHARE_INFO_BYTES = 1
SEQUENCE_BYTES = 4

SIGNER_SIZE = 20
"""[ext] [SPEC §G.1.3] Celestia `SignerSize` = 20 byte.

ĐÂY LÀ NEO CHỐNG MẠO DANH BLOB. Share phiên bản 1 chứa trường signer đặt ngay
sau sequence length trong share đầu, và ĐỒNG THUẬN CELESTIA TỰ KIỂM nó phải
trùng người ký giao dịch. Kẻ ngoài không điền giả được vì phải có khoá riêng.
Nhờ vậy việc lọc blob mạo danh chỉ là so sánh 20 byte — không phép mật mã nào.
Xem §J.2.1."""

FIRST_SHARE_PAYLOAD_V1 = SHARE_SIZE - NAMESPACE_SIZE - SHARE_INFO_BYTES - SEQUENCE_BYTES - SIGNER_SIZE
"""458 byte. Share v0 cho 478; v1 mất thêm 20 byte cho signer."""

CONT_SHARE_PAYLOAD = SHARE_SIZE - NAMESPACE_SIZE - SHARE_INFO_BYTES
"""482 byte."""

CELESTIA_PFB_FIXED_GAS = 65_000
"""[ext] Phí cố định mỗi giao dịch PayForBlobs.

LÀ ĐỒNG MINH CỦA BÊN PHÒNG THỦ: nó khiến 'nhiều blob tí hon' — cách rẻ nhất để
ép worker làm việc vặt — thành cách ĐẮT NHẤT tính trên mỗi byte."""

CELESTIA_GAS_PER_BLOB_BYTE = 8
"""[ext] blob.GasPerBlobByte."""

CELESTIA_MIN_GAS_PRICE_UTIA = 0.002
"""[ext] Phí tối thiểu mặc định, utia mỗi gas."""

CELESTIA_BLOCK_CAP_BYTES = 128 * 1024 * 1024
"""[ext] Sau nâng cấp Matcha (v6): block 8 MiB → 128 MiB, square 128 → 512.

SỰ THẬT QUYẾT ĐỊNH [SPEC §G.1.1]: lượng rác tối đa mỗi cửa sổ là HẰNG SỐ BIẾT
TRƯỚC, không phụ thuộc kẻ tấn công giàu đến đâu. Nên không cần chứng minh 'kẻ
xấu không spam được'; chỉ cần định cỡ worker theo trường hợp xấu nhất đã biết.

CẢNH BÁO: mọi số tính trên 8 MiB đều SAI 16 LẦN. Kiểm lại theo phiên bản mạng."""

CELESTIA_MAX_SQUARE = 512
"""[ext] Square tối đa; mở rộng thành 1024×1024, tức 2048 gốc hàng+cột."""

DATA_SQUARE_ROOTS_MAX = 2 * 2 * CELESTIA_MAX_SQUARE
"""2048 — số gốc hàng + cột mà guest phải nạp để dựng lại data_root (§G.2)."""


class BlobKind(int, Enum):
    """[SPEC §G.1.2] Byte `kind` trong namespace."""

    BUNDLE = 0x01
    CHILD_PROOF = 0x02
    SETTLEMENT = 0x03
    MEMBERSHIP = 0x04


# ═══════════════════════════════════════════════════════════════════════════
# 7. CHI PHÍ zkVM  ·  [SPEC §I.1.6]  — mô hình, KHÔNG chạy mật mã thật
# ═══════════════════════════════════════════════════════════════════════════
#
# [CHỐT — quyết định D3] Bản hiện thực này dùng MÔ HÌNH CHI PHÍ. Bằng chứng là
# đối tượng giả có ĐÚNG KÍCH THƯỚC thật, nên phí DA và calldata là thật. Chỉ nội
# dung mật mã là giả. Nghĩa là: DA thật, EVM thật, kích thước thật.

ZKVM_FIXED_COST_F = 45.385e9
"""[ĐO] f — chi phí nạp và tiền xử lý tệp khoá xác minh 4.738.776 byte.
Nguồn: hồi quy từ điểm đo, R²=1,0000, sai số ngoài mẫu 2,6e-7."""

ZKVM_MARGINAL_COST_M = 11.255e9
"""[ĐO] m — chi phí xác minh MỘT bằng chứng Spartan trong guest."""

POSEIDON2_T3_PERM_US = 11.894
"""[ĐO] Một lần hoán vị Poseidon2 t=3 trên container Xeon 2,1 GHz, đo bằng
`sealbench`. Đặc tả v1 GIẢ ĐỊNH 1,42 µs — sai 8,4 lần."""

POSEIDON2_T8_PERM_US = 27.72
"""[ĐO] Hoán vị t=8 (rate 7). Đắt gấp 2,33 lần t=3 nhưng nuốt 7 phần tử."""

BN254_MUL_NS = 19.96
"""[ĐO] Một phép nhân trường. Kiểm chéo: Poseidon2 t=3 cần ~408 phép nhân →
dự báo 8,14 µs, đo được 11,89 µs. Chênh là phần cộng và hằng số vòng."""

SHA256_SWEEP = (1_000, 5_000, 20_000)
"""[CHỐT — C2-b] Quét ba giá trị thay vì chốt một. Biến ẩn số thành phân tích
độ nhạy, và cho biết phép đo thật cần rơi dưới mức nào.
  1.000  →  3,65 % chi phí một bundle — không đáng kể
  5.000  → 18,27 % — chấp nhận được
 20.000  → 73,07 % — bắt đầu đau"""

SHA256_CYCLES_IN_SP1 = 5_000
"""[MỞ] c_sha — chi phí precompile sha256 trong SP1. CHƯA ĐO.

Quyết định chi phí chứng minh phủ đầy đủ (§G.2.3): 411.200 sha256 mỗi cửa sổ.
  c_sha = 1.000  →  3,65 % chi phí một bundle
  c_sha = 5.000  →  18,27 %   ← mặc định, đoán giữa
  c_sha = 20.000 →  73,07 %
Lệnh đo ở §M.2.3 mục 4. Chạy quét ba giá trị này trong mô phỏng."""

COVERAGE_SHA256_PER_WINDOW = 411_200
"""[SPEC §G.2.3] Trường hợp xấu nhất: W=200 block × (2047 băm dựng data_root
+ 9 băm đường tuple). Có TRẦN — spam nhân tối đa 171 lần rồi dừng."""

# ═══════════════════════════════════════════════════════════════════════════
# 8. KÍCH THƯỚC ARTIFACT  ·  [SPEC §K.1]
# ═══════════════════════════════════════════════════════════════════════════
# Đây là những số làm cho phí DA và calldata THẬT dù nội dung mật mã là giả.

BUNDLE_SIZE_BYTES = 13_776
"""[ĐO] Spartan proof, một hợp đồng một deadline."""

GROTH16_PROOF_BYTES = 356
"""[ĐO] artifact Groth16 thật."""

PUBLIC_VALUES_BYTES = 296
"""[SPEC §D.2.1] 11 trường. Xem public_values.py cho bố cục byte."""

CALLDATA_BYTES = 844
"""[ĐO] 356 + 296 + mào đầu ABI."""

COMMIT_EPOCH_GAS = 487_109
"""[ĐO] Biên lai giao dịch thật. KHÔNG ĐỔI qua bốn bậc độ lớn của N — biến
động 0,0025 %. Đây là toàn bộ đóng góp của Engram gói trong một số."""

CLAIM_SETTLEMENT_GAS_BASE = 24_735
CLAIM_SETTLEMENT_GAS_PER_LEVEL = 514
"""[ĐO] gas ≈ base + per_level·ceil(log2 N). Do NGƯỜI NHẬN trả."""

CLIENT_WITNESS_BYTES = 1_088
"""[SPEC §UC-02] 32 (piece_root) + 32×23 (lên provider_root) + 32×10 (lên
batch_root). Đây là tất cả những gì khách giữ sau khi xoá dữ liệu."""

# ═══════════════════════════════════════════════════════════════════════════
# 9. KINH TẾ  ·  [SPEC §I.1]
# ═══════════════════════════════════════════════════════════════════════════

PROTOCOL_FEE_RATE = 0.02
"""[CHỐT] 2 % ký quỹ. Worker và aggregator gánh chi phí lớn nhất và không có
nguồn thu tự nhiên — không có khoản này thì tính sống dựa vào lòng tốt."""

BOUNTY_RATE = 0.05
"""[CHỐT] Hoa hồng cho người nộp lá phạt hộ.

NGHỊCH LÝ CÓ LỢI: gian lận càng nặng, hoa hồng càng lớn, càng chắc có người săn."""

COLLATERAL_LOCK_EPOCHS = 2
CIRCUIT_BREAKER_THETA = 0.5
"""[MỞ] θ. Chỉ an toàn khi tập worker đủ lớn — nếu mạng chỉ có 16 worker thì
DoS 16 máy là dừng được cả mạng. Ngưỡng số worker tối thiểu CHƯA QUYẾT (§H.1.6)."""

SEALING_FEE_MULTIPLIER = 2.0
"""[CHỐT — B1-a] [SPEC §J.2.4] Phí niêm phong KHÔNG HOÀN LẠI, tính bằng chi phí
CPU của t_seal nhân hệ số này.

VÌ SAO TỒN TẠI: FR-12 nói ký quỹ chưa kiếm được luôn quay về khách. Nhưng nút bỏ
1,28 giờ CPU niêm phong TRƯỚC khi kiếm được đồng nào. Không có khoản này thì
khách mở 1.000 hợp đồng rồi bỏ: nút đốt 1.280 giờ CPU ≈ 12,80 $, khách tốn ~1 $
phí giao dịch và lấy lại toàn bộ ký quỹ.

Khoản này mở khoá cho nút ngay khi nó gọi registerSealed. Nút không niêm phong
thì abortDeal vẫn hoàn đủ cho khách (UC-02 A3). Đối xứng."""

CPU_COST_USD_PER_HOUR = 0.01
"""[CHỐT] Giá CPU dùng để quy ra phí niêm phong và biên kinh tế dựng lại.
Mức cloud spot rẻ — chọn thấp là chọn giả định BẤT LỢI cho phía phòng thủ."""

MIN_COLLATERAL_PER_SLOT_WEI = 10**14
"""[CHỐT — B2-a] [SPEC §J.2.5] Ngưỡng cọc mỗi khe. 1e14 wei = 0,0001 ETH.

VÌ SAO TỒN TẠI: cọc là MỘT KHOẢN MỖI NÚT, không theo hợp đồng. Không có ràng
buộc này thì nút đặt 1 ETH rồi nhận bao nhiêu hợp đồng cũng được; tới ~10.000
hợp đồng thì cọc mỗi hợp đồng tụt dưới ngưỡng §I.1.3 và gian lận thành có lãi.

Hợp đồng cưỡng chế:  available_slots ≤ collateral_wei / MIN_COLLATERAL_PER_SLOT_WEI"""

WORKER_SLOT_CAP_RATIO = 0.05
"""[CHỐT — B3-b] [SPEC §J.2.3] Một worker giữ tối đa 5 % tổng số ô mỗi epoch.

VÌ SAO TỒN TẠI: xổ số worker có trọng số theo cọc và không có trần. Worker nắm
phần p tổng cọc thắng CẢ r=2 khe của một ô với xác suất p², rồi im lặng không
chạy → ô đó UNCOVERED. Nắm 30 % cọc là giết được 69 ô/ngày = 899 hợp đồng mất
doanh thu.

QUY TẮC THOÁT: nếu không đủ worker để phủ hết ô thì nới trần tự động. Ưu tiên
phủ hơn phân tán — một ô không ai nhận còn tệ hơn một worker giữ nhiều ô."""

WORKER_ABSENCE_PENALTY_MODE = "equal_to_damage"
"""[CHỐT — B3-b kèm] Worker vắng mặt bị cắt cọc bằng ĐÚNG doanh thu mà ô đó lẽ
ra tạo ra. Đặc tả trước chỉ ghi 'một phần nhỏ' — không có con số thì không cưỡng
chế được."""

CHILDPROOF_DA_MANDATORY = True
"""[CHỐT — B4-a] [SPEC §J.2.2] MỌI ChildProof PHẢI lên DA (kind=02), và guest
aggregator PHẢI chứng minh phủ đầy đủ trên namespace đó.

VÌ SAO TỒN TẠI: §G.2 giải bài toán phủ đầy đủ ở TẦNG WORKER. Không có cơ chế
tương đương ở TẦNG AGGREGATOR: nó nhận D×S_ns ChildProof, im lặng bỏ một cái, ô
đó thành UNCOVERED, 13 hợp đồng nhận NONE, và nó KHÔNG MẤT GÌ.

Đây là lỗ nghiêm trọng ngang §J.2.1. Vá một nửa rồi để nửa kia hở thì phần bảo
mật mất tính nhất quán.

Chi phí đã biết: 4,31–67,94 $/ngày toàn mạng tuỳ kích thước ChildProof (§H.1.5).
Đổi lại, đường gossip trở thành TỐI ƯU ĐỘ TRỄ chứ không còn là đường chính."""

PIPELINE_DEPTH_L = 2
"""[CHỐT] L — độ sâu đường ống (§F.2.6). Cho phép t_worker + t_agg < L·t_epoch,
đổi lấy quyết toán trễ L epoch.

ĐƯỜNG ỐNG CHỮA ĐỘ TRỄ, KHÔNG CHỮA THÔNG LƯỢNG. Nếu tổng công việc vượt tổng
năng lực thì đường ống chỉ làm hàng đợi dài vô hạn — dùng NFR-05 cho thông lượng."""

# ═══════════════════════════════════════════════════════════════════════════
# 10. NGOÀI PHẠM VI  ·  [SPEC §A.1.2 / UC-01]
# ═══════════════════════════════════════════════════════════════════════════

REED_SOLOMON_K = 4
REED_SOLOMON_N = 6
"""[KHÔNG MÔ PHỎNG] k_RS, n_RS — tham số Reed–Solomon phía khách.

Bản hiện thực này KHÔNG mô phỏng mã hoá RS. Hai hằng số này chỉ để kịch bản ghi
nhận rằng một khối dữ liệu được chia thành n_RS mảnh, mỗi mảnh MỘT hợp đồng
riêng, và dựng lại được từ k_RS mảnh bất kỳ.

── HỆ QUẢ AN TOÀN VẪN ĐÚNG DÙ KHÔNG MÔ PHỎNG ──────────────────────────────

Vì sao RS quan trọng, định lượng: giả sử khách KHÔNG dùng RS mà chỉ lập ba hợp
đồng với cùng nội dung byte. Ba hợp đồng có cùng piece_root, nên một bên nắm cả
ba nút chỉ cần lưu MỘT bản thô cộng ba bộ {R,S} mỗi bộ 1,6 %:

    32 GiB + 1,5 GiB   thay vì   96 GiB   →   tiết kiệm 66 %

và vẫn qua mọi thách thức, vì mỗi hợp đồng được xét ĐỘC LẬP và bản nào cũng trả
lời đúng. Khách trả tiền ba bản, nhận độ bền của một.

RS đóng đúng lỗ đó: n_RS mảnh có nội dung KHÁC NHAU nên piece_root khác nhau,
nên một máy giữ ba mảnh vẫn phải giữ BA LẦN dữ liệu.

Phát biểu tổng quát: mỗi bản phải có piece_root khác nhau. RS là một cách đạt
được; mã hoá bằng khoá riêng mỗi bản là cách khác. GIAO THỨC KHÔNG CƯỠNG CHẾ
ĐƯỢC — nó là giới hạn, không phải cơ chế (§J.1.4).

Dư thừa về SỰ CỐ thì không cách nào thành lập được: giao thức không chứng minh
được n nút là n máy, n nguồn điện, n vùng địa lý.

Ký hiệu k_RS, n_RS để không lẫn với k_act / k_mix / k_delay (§A.7)."""


def assert_distinct_piece_roots(piece_roots: list[bytes]) -> None:
    """[SPEC UC-01] Công cụ phía khách: kiểm các mảnh có piece_root khác nhau.

    Với RS đúng chuẩn thì điều này tự động đúng — n_RS mảnh có nội dung khác
    nhau. Hàm này để bắt lỗi khi khách vô tình lập nhiều hợp đồng trùng nội dung.

    KHÔNG phải ràng buộc giao thức: hợp đồng EVM không kiểm và không kiểm được.
    """
    if len(set(piece_roots)) != len(piece_roots):
        raise ValueError(
            "Các mảnh có piece_root trùng nhau — nghĩa là trùng nội dung byte. "
            "Một bên nắm nhiều nút sẽ khử trùng lặp bản thô và bạn mất phần lớn "
            "độ bền đã trả tiền. Xem UC-01 ghi chú thiết kế."
        )
