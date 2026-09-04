"""[SPEC §K.1] Cấu hình worker."""

from __future__ import annotations

import os
from dataclasses import dataclass

from engram_common.constants import PROFILE_PRODUCTION, PROFILE_SIM, TimingProfile


@dataclass(frozen=True)
class WorkerConfig:
    name: str
    chain_mode: str
    chain_rpc: str
    celestia_rpc: str
    profile: TimingProfile
    genesis_height: int
    n_shards: int
    sha_cycles: int
    listen_port: int = 8080

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        return cls(
            name=os.getenv("WORKER_NAME", "W_1"),
            chain_mode=os.getenv("CHAIN_MODE", "local"),
            chain_rpc=os.getenv("CHAIN_RPC", "http://anvil:8545"),
            celestia_rpc=os.getenv("CELESTIA_RPC", "http://da-mock:8080"),
            profile=PROFILE_SIM if os.getenv("ENGRAM_PROFILE", "sim") == "sim" else PROFILE_PRODUCTION,
            genesis_height=int(os.getenv("GENESIS_HEIGHT", "1000000")),
            n_shards=int(os.getenv("N_SHARDS", "2")),
            # [CHỐT C2-b] c_sha chưa đo. Orchestrator quét ba giá trị và xuất ba
            # cột, biến ẩn số thành phân tích độ nhạy.
            sha_cycles=int(os.getenv("SHA_CYCLES", "5000")),
        )
