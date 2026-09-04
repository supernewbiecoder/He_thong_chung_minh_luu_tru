"""Điểm vào dịch vụ. `python -m provider`"""

import logging
import os

import uvicorn

from .api import build_app
from .config import ProviderConfig


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "info").upper(),
        format="%(asctime)s %(levelname)s [provider] %(message)s",
    )
    cfg = ProviderConfig.from_env()
    logging.info("khởi động nút %s · chuỗi %s · hồ sơ %s", cfg.name, cfg.chain_mode, cfg.profile.name)
    uvicorn.run(build_app(cfg), host="0.0.0.0", port=cfg.listen_port, log_level="warning")


if __name__ == "__main__":
    main()
