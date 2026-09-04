"""[SPEC §K.1] Cấu hình dịch vụ nút. Đọc từ biến môi trường, không có giá trị
bí mật nào hard-code."""

from __future__ import annotations

import os
from dataclasses import dataclass

from engram_common.constants import PROFILE_PRODUCTION, PROFILE_SIM, TimingProfile


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    celestia_address: bytes          # 20 B — [SPEC §J.2.1] NEO CHỐNG MẠO DANH
    chain_mode: str                  # local | mocha-anvil | mocha-sepolia
    chain_rpc: str
    celestia_rpc: str
    profile: TimingProfile
    genesis_height: int
    capacity_slots: int
    sim_chunks_per_deal: int
    listen_port: int = 8080

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        prof = PROFILE_SIM if os.getenv("ENGRAM_PROFILE", "sim") == "sim" else PROFILE_PRODUCTION
        addr = os.getenv("CELESTIA_ADDRESS", "celestia1aaaa")
        return cls(
            name=os.getenv("PROVIDER_NAME", "P_a"),
            # Băm chuỗi bech32 xuống 20 byte cho mô phỏng. Khi chạy thật phải
            # giải mã bech32 để lấy đúng 20 byte mà Celestia ghi vào share v1.
            celestia_address=__import__("hashlib").sha256(addr.encode()).digest()[:20],
            chain_mode=os.getenv("CHAIN_MODE", "local"),
            chain_rpc=os.getenv("CHAIN_RPC", "http://anvil:8545"),
            celestia_rpc=os.getenv("CELESTIA_RPC", "http://celestia:26658"),
            profile=prof,
            genesis_height=int(os.getenv("GENESIS_HEIGHT", "1000000")),
            capacity_slots=int(os.getenv("CAPACITY_SLOTS", "1024")),
            # [MỞ — xem báo cáo] Sector thật là 8.388.608 chunk = 32 GiB. Với 20
            # hợp đồng thì là 640 GiB, không mô phỏng nổi. Ở chế độ sim ta dùng
            # sector ảo nhỏ, và SINH nội dung chunk theo yêu cầu từ một hạt giống
            # thay vì lưu ra đĩa — xem storage.py.
            sim_chunks_per_deal=int(os.getenv("SIM_CHUNKS_PER_DEAL", "1024")),
        )
