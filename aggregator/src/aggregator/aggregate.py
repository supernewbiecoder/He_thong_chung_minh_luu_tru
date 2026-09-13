"""
[SPEC §F.2.3] Gộp epoch  ·  [CHỐT B4-a] [SPEC §J.2.2] Phủ đầy đủ tầng aggregator
"""

from __future__ import annotations

from dataclasses import dataclass

from engram_common.blob import BlobKind, build_namespace
from engram_common.clock import PublicValues
from engram_common.constants import GROTH16_PROOF_BYTES
from engram_common.crypto import keccak, merkle_root
from engram_common.verdict import Verdict

from .reconcile import EpochVerdicts, reconcile_shard_results, SnapshotMismatch


@dataclass(frozen=True)
class SettlementLeaf:
    """[SPEC §D.1.6] Một dòng phán quyết cho đúng một hợp đồng trong đúng một epoch.

    Là VÉ RÚT TIỀN. Hợp đồng EVM không tự phân phối; ai muốn nhận thì cầm lá này
    cùng đường Merkle lên nộp.

    Guest SP1 TỰ TÍNH lá từ biến verdict bên trong mạch — host không nhận lá từ
    ngoài rồi đưa vào, nên không sửa được phán quyết sau khi zkVM đã chạy xong.
    """

    epoch: int
    provider_id: bytes      # 20 B — chính là địa chỉ EVM của nút
    deal_id: bytes          # 32 B
    verdict: Verdict
    challenges_total: int
    challenges_passed: int
    reward_wei: int
    slash_wei: int

    LEAF_TAG = b"ENGRAM_LEAF_V1"

    def digest(self) -> bytes:
        """[SPEC §D.1.6 — SỬA D1] Ảnh trước của lá, PHẢI khớp bit-để-bit với
        `_leafDigest` trong EngramManager.sol.

        BA THAY ĐỔI SO VỚI BẢN TRƯỚC, và mỗi cái vá một lỗ:

        ① `epoch` nằm trong ảnh trước. Không có nó, hai epoch sinh ra lá giống
           hệt nhau sẽ cho cùng digest, mà `settlementClaimed` đánh dấu theo
           digest, nên lá thứ hai vĩnh viễn không rút được.

        ② BIG-endian thay vì little. Không phải chuyện thẩm mỹ: `abi.encodePacked`
           của Solidity là big-endian, nên little-endian bắt hợp đồng phải đảo
           byte thủ công, và mỗi chỗ đảo là một chỗ sai được.

        ③ Nhãn miền `ENGRAM_LEAF_V1` ở đầu. Cùng với tiền tố 0x01 của nút trong
           trong `crypto._node`, nó làm ảnh trước của lá không bao giờ trùng dạng
           ảnh trước của nút trong, nên không ai trình được một nút trong ra như
           thể nó là lá.

        Nhưng thay đổi QUAN TRỌNG NHẤT không nằm ở đây mà ở hợp đồng: trước đây
        hợp đồng nhận `leafDigest` đã băm sẵn và chỉ leo cây Merkle, nên nó không
        hề ràng buộc digest đó với số tiền và người nhận được truyền vào. Giờ hợp
        đồng tự băm lại từ các trường, nên digest và số tiền không thể rời nhau.
        """
        assert len(self.provider_id) == 20, "provider_id phải là địa chỉ 20 byte"
        assert len(self.deal_id) == 32, "deal_id phải 32 byte"
        return keccak(
            self.LEAF_TAG,
            self.epoch.to_bytes(8, "big"),
            self.provider_id,
            self.deal_id,
            bytes([int(self.verdict)]),
            self.challenges_total.to_bytes(4, "big"),
            self.challenges_passed.to_bytes(4, "big"),
            self.reward_wei.to_bytes(32, "big"),
            self.slash_wei.to_bytes(32, "big"),
        )


class CoverageGapError(RuntimeError):
    """[CHỐT B4-a] Aggregator KHÔNG được nộp khi thiếu ChildProof của một mảnh.

    Đây là bản vá cho §J.2.2 — lỗ nghiêm trọng thứ hai. Không có nó, aggregator
    im lặng bỏ một ChildProof, mảnh đó thành UNCOVERED, các hợp đồng trong mảnh
    nhận NONE, và aggregator KHÔNG MẤT GÌ.

    §G.2 đã đóng lỗ này ở TẦNG WORKER. Đóng một nửa rồi để nửa kia hở thì phần
    bảo mật mất tính nhất quán — người phản biện sẽ hỏi đúng câu "thế còn tầng
    aggregator?".

    Cách đóng: mọi ChildProof PHẢI lên DA (kind=02), và guest aggregator PHẢI
    chứng minh phủ đầy đủ trên namespace đó, đúng như worker làm với kind=01.
    Chi phí đã biết: 4,31–67,94 $/ngày toàn mạng.
    """


# ═══════════════════════════════════════════════════════════════════════════
#  GẤP DẦN THEO TỪNG DEADLINE  ·  [T4.1]
# ═══════════════════════════════════════════════════════════════════════════
#
# VÌ SAO. `aggregate_epoch` nhận TOÀN BỘ ChildProof của cả epoch trong một lần
# gọi, tức aggregator không làm gì suốt 24 giờ rồi dồn hết vào cuối. Nhưng chính
# docstring của mô-đun nói nó gộp theo CÂY ĐỆ QUY, mà cây đệ quy thì gộp dần
# được: gộp hai lá thành một nút ngay khi có đủ hai lá.
#
# ĐƯỜNG TỚI HẠN CO LẠI. Thay vì
#     t_worker(ô cuối) + t_agg(gộp 480 ô)
# nó thành
#     t_worker(ô cuối) + t_agg(gộp S_ns ô) + t_agg(gộp D nút)
# 47 phần gộp kia đã xong từ trước, chạy rải suốt epoch.
#
# BA LỢI ÍCH KHÁC. Tải phần cứng phẳng hơn thay vì đòi năng lực khổng lồ trong
# vài giờ cuối; phát hiện thiếu ChildProof ngay sau deadline đó thay vì gần hết
# ngày; và không phải giữ 480 ChildProof trong bộ nhớ cùng lúc.
#
# CẢNH BÁO. Các phần gộp cách nhau tới 24 giờ, nên nguy cơ lệch sổ CAO HƠN so
# với gộp một lần. `DeadlineFold` vì thế mang `snapshot_id`, và
# `aggregate_epoch_incremental` đòi mọi phần gộp cùng một giá trị — đúng cùng
# ràng buộc đã áp cho ChildProof.


@dataclass
class DeadlineFold:
    """Kết quả gộp một deadline. Tương đương một nút trong cây đệ quy."""

    deadline: int
    snapshot_id: bytes
    shard_results: list
    """Giữ nguyên ChildProof để tầng trên đối chiếu lại. Trong bản thật đây là
    một bằng chứng đệ quy, không phải danh sách."""

    @property
    def n_shards_covered(self) -> int:
        return len({r.shard for r in self.shard_results})


def fold_deadline(*, deadline: int, snapshot_id: bytes, shard_results: list,
                  n_shards: int) -> DeadlineFold:
    """Gộp các ô của MỘT deadline, chạy ngay sau khi cửa sổ deadline đó đóng.

    Kiểm tại chỗ hai thứ mà nếu để tới cuối epoch mới kiểm thì đã muộn 20 giờ:
    đủ mảnh, và mọi ChildProof cùng một sổ.
    """
    for r in shard_results:
        if r.deadline != deadline:
            raise CoverageGapError(
                f"ChildProof của deadline {r.deadline} lọt vào phần gộp của {deadline}"
            )
        if r.snapshot_id != snapshot_id:
            raise SnapshotMismatch(
                f"ô ({r.deadline},{r.shard}) dùng sổ {r.snapshot_id.hex()[:16]} "
                f"trong khi phần gộp dùng {snapshot_id.hex()[:16]}"
            )

    covered = {r.shard for r in shard_results}
    missing = set(range(n_shards)) - covered
    if missing:
        raise CoverageGapError(
            f"deadline {deadline} thiếu mảnh {sorted(missing)} — phát hiện NGAY "
            f"sau deadline này, không phải tới cuối epoch"
        )
    return DeadlineFold(deadline=deadline, snapshot_id=snapshot_id,
                        shard_results=list(shard_results))


def aggregate_epoch_incremental(*, folds: list[DeadlineFold], **kw):
    """Gộp tầng trên từ các phần gộp theo deadline.

    Kết quả PHẢI trùng với `aggregate_epoch` chạy trên cùng tập ChildProof — có
    test chốt điều đó, vì nếu hai đường cho hai kết quả thì cả hai đều đáng ngờ.
    """
    if not folds:
        raise CoverageGapError("không có phần gộp nào")

    sid = folds[0].snapshot_id
    for f in folds:
        if f.snapshot_id != sid:
            raise SnapshotMismatch(
                f"phần gộp deadline {f.deadline} dùng sổ khác các phần còn lại"
            )

    flat = [r for f in folds for r in f.shard_results]
    return aggregate_epoch(shard_results=flat, snapshot_id=sid, **kw)


def aggregate_epoch(
    *,
    epoch: int,
    chain_id: int,
    shard_results: list,
    deadlines_per_epoch: int,
    n_shards: int,
    prev_state_root: bytes,
    da_commitment: bytes,
    da_nonce: int,
    submitter: bytes,
    storage_vk_digest: bytes,
    snapshot_id: bytes,
    require_full_coverage: bool = True,
) -> tuple[PublicValues, bytes, list[SettlementLeaf]]:
    """Gộp cả epoch thành 297 byte public values + bằng chứng Groth16 356 byte."""

    ev: EpochVerdicts = reconcile_shard_results(shard_results)

    # [CHỐT B4-a] Phủ đầy đủ ở TẦNG AGGREGATOR.
    #
    # Kiểm theo Ô, không theo SỐ BẢN. Với r=2, một worker chết thì ô vẫn được
    # phủ bởi worker còn lại — đó chính là điều dư thừa sinh ra để làm. Đòi đủ
    # r bản là làm lẫn lộn AN TOÀN với TÍNH SỐNG, và biến một worker chết thành
    # void cả epoch.
    # ── TẬP Ô KỲ VỌNG: DẪN XUẤT, KHÔNG NHẬN  [SỬA P0.3] ────────────────────
    #
    # Bản trước nhận `expected_cells` làm THAM SỐ từ host. Đó đúng là lỗ hổng
    # mà §D.3 vá ở tầng worker, chỉ lùi lên một tầng: host đưa vào một tập đã
    # bớt một ô thì `missing` rỗng, không ai báo lỗi, và các hợp đồng trong ô
    # đó lặng lẽ không có phán quyết.
    #
    # Lưới ô là TẤT ĐỊNH từ ba tham số giao thức, nên dẫn xuất được tại chỗ.
    # `deadlines_per_epoch` và `n_shards` là hằng số cấu hình mà hợp đồng cũng
    # biết, nên host nói dối về chúng thì lệch ngay ở mắt xích ④.
    expected_cells = {
        (epoch * 1_000_000 + d, s)
        for d in range(deadlines_per_epoch)
        for s in range(n_shards)
    }

    if require_full_coverage:
        missing = expected_cells - ev.covered_cells
        if missing:
            raise CoverageGapError(
                f"thiếu ChildProof cho {len(missing)} ô: {sorted(missing)[:3]}…"
            )
        extra = ev.covered_cells - expected_cells
        if extra:
            # Ô ngoài tập kỳ vọng: worker nhồi thêm để đẩy num_verified lên.
            raise CoverageGapError(
                f"có ChildProof cho {len(extra)} ô KHÔNG thuộc epoch này: "
                f"{sorted(extra)[:3]}…"
            )

    # Guest TỰ TÍNH results_root từ biến verdict — không nhận từ host.
    leaves: list[SettlementLeaf] = []
    for (pid, did), v in sorted(ev.verdicts.items()):
        leaves.append(
            SettlementLeaf(
                epoch=epoch,
                provider_id=pid,
                deal_id=did,
                verdict=v,
                challenges_total=16,
                challenges_passed=16 if v is Verdict.PASS else 0,
                reward_wei=10**12 if v is Verdict.PASS else 0,
                slash_wei=10**13 if v is Verdict.FAIL else 0,
            )
        )
    results_root = merkle_root([lf.digest() for lf in leaves])

    # ── MẮT XÍCH ④ [SỬA — nhận xét phản biện P0.3] ─────────────────────────
    #
    # num_verified phải lấy từ SỔ, không lấy từ số lá guest tự sinh ra.
    #
    # `len(leaves)` đếm phán quyết mà guest TẠO RA. Một guest sai hoặc gian có
    # thể tạo ra đúng số lá mà nội dung chẳng liên quan gì tới nghĩa vụ thật —
    # ví dụ bỏ hẳn một mảnh rồi đánh NONE cho mọi hợp đồng trong đó.
    #
    # Σ|E_cell| thì khác: mỗi |E_cell| dựng từ sổ thành viên đã đối chiếu
    # snapshot_id, và reconcile_shard_results đã kiểm từng ô trả về đúng bản số.
    # Nên tổng này là hệ quả của SỔ, không phải của guest.
    # ── Khép kín chuỗi sổ  [SỬA P0.3] ──────────────────────────────────────
    #
    # reconcile đã buộc mọi ChildProof mang CÙNG một snapshot_id. Ở đây buộc
    # tiếp giá trị chung đó bằng snapshot_id đi vào public values, tức bằng giá
    # trị hợp đồng đã đóng băng. Thiếu bước này thì cả epoch có thể nhất quán
    # nội bộ mà dựa trên một sổ không phải sổ on-chain.
    if ev.snapshot_id is not None and ev.snapshot_id != snapshot_id:
        raise SnapshotMismatch(
            f"ChildProof dùng sổ {ev.snapshot_id.hex()[:16]} nhưng public values "
            f"khai {snapshot_id.hex()[:16]}"
        )

    num_verified = sum(ev.cell_expected.values())

    if num_verified != len(leaves):
        # Không bao giờ xảy ra nếu các phép kiểm trên đã chạy — giữ lại như
        # một chốt chặn cuối, vì đây là bất biến quan trọng nhất của cả hệ.
        raise CoverageGapError(
            f"Σ|E_cell| = {num_verified} nhưng có {len(leaves)} lá quyết toán"
        )


    # ── ĐỘ LẤP ĐẦY CỬA SỔ [SPEC §H.1.7] ────────────────────────────────────
    #
    # Lấy giá trị LỚN NHẤT trong các ô, không lấy trung bình. Lý do: chỉ cần
    # MỘT cửa sổ bị lấp đầy là các nút thuộc deadline đó đã có thể bị chặn
    # không đăng được bằng chứng. Lấy max là hướng thận trọng — nó chỉ dẫn tới
    # việc KHÔNG trả hoa hồng, chứ không dẫn tới việc phạt oan ai.
    #
    # Không sợ worker khai khống: giá trị này do guest tính từ kích thước
    # square của block Celestia, tức từ dữ liệu đã cam kết, không phải lời khai.
    window_saturation = max(
        (r.coverage.window_saturation for r in shard_results if r.coverage is not None),
        default=0,
    )

    # [SPEC §J.1.1] Chuỗi trạng thái — mọi trường quan trọng phải nằm trong đó,
    # nếu không chúng có thể đổi mà không ai phát hiện khi kiểm lại từ đầu.
    new_state_root = keccak(
        prev_state_root,
        epoch.to_bytes(8, "little"),
        results_root,
        da_commitment,
        snapshot_id,
    )

    pv = PublicValues(
        epoch=epoch,
        batch_root=merkle_root([r.results_root for r in shard_results]),
        da_commitment=da_commitment,
        da_nonce=da_nonce,
        results_root=results_root,
        results_data_root=keccak(b"RESULTS_DA", results_root),
        storage_vk_digest=storage_vk_digest,
        snapshot_id=snapshot_id,
        submitter=submitter,
        prev_state_root=prev_state_root,
        new_state_root=new_state_root,
        num_verified=num_verified,   # từ Σ|E_cell|, KHÔNG phải len(leaves)
        window_saturation=window_saturation,
    )

    # [CHỐT D3] Bằng chứng giả có ĐÚNG kích thước thật, nên calldata và gas THẬT.
    proof = bytes(GROTH16_PROOF_BYTES)
    return pv, proof, leaves


def childproof_namespace(chain_id: int) -> bytes:
    """[CHỐT B4-a] Namespace cho ChildProof. Aggregator đọc TOÀN BỘ namespace này
    và chứng minh phủ đầy đủ, đúng như worker làm với namespace bundle."""
    return build_namespace(BlobKind.CHILD_PROOF, chain_id, 0)
