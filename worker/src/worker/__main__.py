"""Điểm vào dịch vụ worker. `python -m worker`"""

import logging
import os
from typing import Any

import uvicorn
from fastapi import FastAPI

from .config import WorkerConfig


def build_app(cfg: WorkerConfig) -> FastAPI:
    app = FastAPI(title=f"engram-worker[{cfg.name}]", version="0.1.0")

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {
            "service": "worker",
            "name": cfg.name,
            "chain_mode": cfg.chain_mode,
            "shards": cfg.n_shards,
            "sha_cycles": cfg.sha_cycles,
        }

    return app


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "info").upper(),
        format="%(asctime)s %(levelname)s [worker] %(message)s",
    )
    cfg = WorkerConfig.from_env()
    logging.info("khởi động worker %s · %d mảnh", cfg.name, cfg.n_shards)
    uvicorn.run(build_app(cfg), host="0.0.0.0", port=cfg.listen_port, log_level="warning")


if __name__ == "__main__":
    main()
