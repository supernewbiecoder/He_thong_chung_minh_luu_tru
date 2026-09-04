"""
[CHỐT E4] Celestia giả, chỉ dùng ở giai đoạn 1 của docs/KIEM_THU.md.

 ── ĐIỀU PHẢI NHỚ ────────────────────────────────────────────────────────

 Mock này tự điền trường `signer`, nên nó KHÔNG chứng minh được điều mà §J.2.1
 dựa vào: rằng đồng thuận Celestia THẬT SỰ áp đặt trường đó. Chỉ Mocha mới
 chứng minh được. Xem docs/KIEM_THU.md giai đoạn 2.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from engram_common.blob import pfb_fee_utia, pfb_gas, shares_for


@dataclass
class StoredBlob:
    height: int
    index: int
    namespace: str
    signer: str
    data_hex: str


@dataclass
class Chain:
    """Chiều cao tăng đều. ĐÂY LÀ ĐỒNG HỒ CỦA CẢ HỆ [SPEC §F.1.2] — mọi dịch vụ
    hỏi chiều cao ở đây, không dịch vụ nào gọi time.time() cho logic giao thức."""

    height: int = 1_000_000
    block_time_s: float = 1.0
    blobs: list[StoredBlob] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def tick(self) -> None:
        while True:
            time.sleep(self.block_time_s)
            with self._lock:
                self.height += 1


class SubmitRequest(BaseModel):
    namespace: str
    data_hex: str
    signer: str  # 20 B hex — Celestia thật áp đặt trường này, mock thì tin lời


def main() -> None:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s [da-mock] %(message)s")
    chain = Chain(
        height=int(os.getenv("GENESIS_HEIGHT", "1000000")),
        block_time_s=float(os.getenv("BLOCK_TIME_S", "1.0")),
    )
    threading.Thread(target=chain.tick, daemon=True).start()

    app = FastAPI(title="engram-da-mock", version="0.1.0")

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"service": "da-mock", "height": chain.height, "blobs": len(chain.blobs)}

    @app.get("/v1/height")
    def height() -> dict[str, int]:
        return {"height": chain.height}

    @app.post("/v1/blob/submit")
    def submit(req: SubmitRequest) -> dict[str, Any]:
        payload = bytes.fromhex(req.data_hex)
        with chain._lock:
            h = chain.height
            idx = sum(1 for b in chain.blobs if b.height == h)
            chain.blobs.append(StoredBlob(h, idx, req.namespace, req.signer, req.data_hex))
        return {
            "height": h,
            "index": idx,
            "shares": shares_for(len(payload)),
            "gas": pfb_gas(len(payload)),
            "fee_utia": pfb_fee_utia(len(payload)),
        }

    @app.get("/v1/blob/range")
    def get_range(namespace: str, start: int, end: int) -> dict[str, Any]:
        """Đọc mọi blob trong một namespace, trong cửa sổ chiều cao.

        Namespace MỞ: trả về mọi thứ ai đó đã ghi vào, kể cả rác. Đúng như
        Celestia — và đó chính là lý do worker phải lọc theo trường signer.
        """
        out = [
            {"height": b.height, "index": b.index, "signer": b.signer, "data_hex": b.data_hex}
            for b in chain.blobs
            if b.namespace == namespace and start <= b.height < end
        ]
        return {"namespace": namespace, "count": len(out), "blobs": out}

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")


if __name__ == "__main__":
    main()
