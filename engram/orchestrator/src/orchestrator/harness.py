"""
═══════════════════════════════════════════════════════════════════════════════
 Khung chạy trong tiến trình — CHỈ DÙNG KHI MÔ PHỎNG
═══════════════════════════════════════════════════════════════════════════════

 Chạy toàn bộ bốn tầng trong MỘT tiến trình Python, không cần Docker, không cần
 mạng. Mục đích: vòng lặp phát triển nhanh và test tất định.

 Bản triển khai thật dùng HTTP giữa các dịch vụ, và `docker compose` dựng chúng
 riêng biệt. Khung này KHÔNG thay thế điều đó — nó chỉ cho phép chạy kịch bản
 mà không phải dựng bảy container. Xem docs/KIEM_THU.md giai đoạn 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engram_common.blob import BlobHeader, BlobKind, ObservedBlob, build_namespace
from engram_common.clock import Clock
from engram_common.constants import BUNDLE_SIZE_BYTES, PROFILE_SIM, SECTOR_PROFILES
from engram_common.crypto import derive_beacon, derive_deadline, derive_shard, keccak
from engram_common.verdict import Verdict


@dataclass
class InMemoryDA:
    """Celestia trong bộ nhớ. Namespace MỞ — ai cũng ghi vào được, kể cả rác.

    Đúng như Celestia thật, và đó chính là lý do worker phải lọc theo người ký.
    """

    height: int = 1_000_000
    # (namespace, blob) — ObservedBlob là frozen nên namespace giữ ở ngoài.
    entries: list[tuple[bytes, ObservedBlob]] = field(default_factory=list)

    def advance(self, n: int = 1) -> int:
        self.height += n
        return self.height

    def submit(self, namespace: bytes, header: BlobHeader, payload: bytes, signer: bytes) -> None:
        idx = sum(1 for ns, b in self.entries if b.height == self.height)
        self.entries.append((namespace, ObservedBlob(self.height, idx, signer, header, payload)))

    def read(self, namespace: bytes, start: int, end: int) -> list[ObservedBlob]:
        """Namespace MỞ: trả về mọi thứ ai đó đã ghi vào, kể cả rác. Đúng như
        Celestia — và đó chính là lý do worker phải lọc theo người ký."""
        return [b for ns, b in self.entries if ns == namespace and start <= b.height < end]

    def data_roots(self, heights: list[int]) -> list[bytes]:
        """data_root của mỗi block — trong bản thật là gốc của data square."""
        return [keccak(b"DATA_ROOT", h.to_bytes(8, "little")) for h in heights]


@dataclass
class SimDeal:
    deal_id: bytes
    provider_id: bytes
    provider_celestia: bytes
    sealed_root: bytes
    deadline_idx: int
    shard: int
    lost: bool = False       # nút mất dữ liệu — vẫn đăng blob nhưng bằng chứng sai → FAIL
    offline: bool = False    # nút im lặng, không đăng gì → ABSENT (được CHỨNG MINH)
    declared: bool = False   # nút tự khai trước deadline (UC-04) → phạt nhẹ hơn


@dataclass
class SimNetwork:
    """Mạng mô phỏng: nút, hợp đồng, worker, DA."""

    n_deals: int
    n_shards: int
    n_providers: int = 4
    n_workers: int = 60          # ≥ 40 để trần khe ràng buộc — xem §J.2.3
    sector: str = "tiny"
    sha_cycles: int = 5_000
    chain_id: int = 0x00AA36A7

    # [CHỐT F2] t_worker ước lượng. Ở N=10.000 một ô tốn ~192e9 chu kỳ; với
    # worker chạy ~17 Mcycle/s thì t_worker ≈ 3,1 giờ. Ở hồ sơ sim deadline chỉ
    # 60 giây nên cooldown tính theo tỉ lệ tương đương.
    t_worker_seconds: float = 3.1 * 3600
    dead_workers: set = field(default_factory=set)

    da: InMemoryDA = field(default_factory=InMemoryDA)
    deals: list[SimDeal] = field(default_factory=list)
    signer_of: dict[bytes, bytes] = field(default_factory=dict)
    clock: Clock | None = None
    worker_pool: list = field(default_factory=list)
    assigned: dict = field(default_factory=dict)
    lottery_stats: object = None
    cooldown: int = 0

    def build(self) -> "SimNetwork":
        from worker.lottery import LotteryStats, WorkerEntry, cooldown_deadlines, required_workers

        self.clock = Clock(PROFILE_SIM, self.da.height)
        # Tỉ lệ t_worker / deadline giữ nguyên như ở hồ sơ production, để
        # cooldown mô phỏng phản ánh đúng tình huống thật.
        deadline_s_prod = 300 * 6.0
        self.cooldown = cooldown_deadlines(self.t_worker_seconds, deadline_s_prod)
        self.worker_pool = [
            WorkerEntry(bytes([i]), 10**18) for i in range(self.n_workers)
        ]
        self.lottery_stats = LotteryStats()
        self.required_workers = required_workers(self.n_shards, 2, self.cooldown)
        D = PROFILE_SIM.deadlines_per_epoch
        for i in range(self.n_deals):
            pidx = i % self.n_providers
            pid = keccak(b"PROVIDER", pidx.to_bytes(2, "little"))[:20]
            cel = keccak(b"CELESTIA", pidx.to_bytes(2, "little"))[:20]
            self.signer_of[pid] = cel
            did = keccak(b"DEAL", i.to_bytes(4, "little"))
            self.deals.append(
                SimDeal(
                    deal_id=did,
                    provider_id=pid,
                    provider_celestia=cel,
                    sealed_root=keccak(b"SEALED", did),
                    deadline_idx=derive_deadline(did, D),   # [CHỐT E3]
                    shard=derive_shard(did, self.n_shards),
                )
            )
        return self

    def namespace(self, shard: int) -> bytes:
        return build_namespace(BlobKind.BUNDLE, self.chain_id, shard)

    def publish_bundles(self, deadline_abs: int, deals: list[SimDeal]) -> None:
        """Nút sinh bundle và ĐĂNG LÊN CELESTIA — không gửi lên EVM."""
        for d in deals:
            if d.offline:
                # Không đăng gì. Nhờ chứng cứ phủ đầy đủ §G.2, worker KẾT LUẬN
                # ĐƯỢC là vắng mặt — không phải khai, mà là chứng minh.
                continue
            if d.lost:
                # Nút mất dữ liệu vẫn có thể đăng blob, nhưng bằng chứng sai.
                payload = b"\xff" * BUNDLE_SIZE_BYTES
            else:
                payload = d.sealed_root + bytes(BUNDLE_SIZE_BYTES - 32)
            hdr = BlobHeader(BlobKind.BUNDLE, deadline_abs, d.shard,
                             d.provider_id, d.deal_id, len(payload))
            self.da.submit(self.namespace(d.shard), hdr, payload, d.provider_celestia)

    def publish_decoys(self, deadline_abs: int, target: SimDeal, count: int) -> None:
        """[SPEC §J.2.1] Kẻ ngoài mạo danh — nhãn thật, người ký giả.

        Khoá (provider_id, deal_id) là CÔNG KHAI trên chuỗi, namespace KHÔNG CÓ
        CHỦ. Nên việc này làm được với giá 0,00024 $ mỗi blob.
        """
        attacker = keccak(b"ATTACKER")[:20]
        for _ in range(count):
            hdr = BlobHeader(BlobKind.BUNDLE, deadline_abs, target.shard,
                             target.provider_id, target.deal_id, BUNDLE_SIZE_BYTES)
            self.da.submit(self.namespace(target.shard), hdr,
                           b"\xff" * BUNDLE_SIZE_BYTES, attacker)

    def beacon(self, slot) -> bytes:
        return derive_beacon(self.da.data_roots(self.clock.beacon_heights(slot)))
