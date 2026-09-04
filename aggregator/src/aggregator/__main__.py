"""Điểm vào dịch vụ aggregator. `python -m aggregator`"""

import logging
import os
from typing import Any

import uvicorn
from fastapi import FastAPI


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "info").upper(),
        format="%(asctime)s %(levelname)s [aggregator] %(message)s",
    )
    mandatory = os.getenv("CHILDPROOF_DA_MANDATORY", "true").lower() == "true"
    app = FastAPI(title="engram-aggregator", version="0.1.0")

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {
            "service": "aggregator",
            "name": os.getenv("AGGREGATOR_NAME", "A_1"),
            # [CHỐT B4-a] Tắt cờ này là mở lại lỗ §J.2.2.
            "childproof_da_mandatory": mandatory,
        }

    logging.info("khởi động aggregator · phủ đầy đủ ChildProof: %s", mandatory)
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")


if __name__ == "__main__":
    main()
