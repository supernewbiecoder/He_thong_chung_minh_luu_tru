"""
═══════════════════════════════════════════════════════════════════════════════
 watchtower — GIÁM SÁT
 [SPEC §A.2 vai trò 5] · [SPEC §A.4.1]
═══════════════════════════════════════════════════════════════════════════════

 ── VAI TRÒ ĐÃ ĐỔI TRONG v2, VÀ ĐÂY LÀ ĐIỂM QUAN TRỌNG ──────────────────

 Bản v1 đặt watchtower TRONG giả định an toàn: cần "ít nhất một watchtower
 trung thực và đang thức" để phát hiện aggregator giấu blob rồi khai ABSENT.

 Sau §G.2, guest TỰ CHỨNG MINH phủ đầy đủ, nên ABSENT thành kết luận được
 chứng minh chứ không phải lời khai. Watchtower RỜI KHỎI giả định an toàn.

 Nó chỉ còn vai trò TÍNH SỐNG: nhắc khi aggregator im lặng quá lâu. Watchtower
 chết thì không ai mất tiền, chỉ chậm hơn khi có sự cố.

 Đây là khác biệt lớn: một thành phần nằm trong giả định an toàn phải luôn
 sống; một thành phần chỉ lo tính sống thì không.
"""

import logging, os
from typing import Any
import uvicorn
from fastapi import FastAPI


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper(),
                        format="%(asctime)s %(levelname)s [watchtower] %(message)s")
    app = FastAPI(title="engram-watchtower", version="0.1.0")

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {
            "service": "watchtower",
            # Ghi thẳng vào health để không ai tưởng nhầm nó là bộ phận an toàn.
            "role": "tinh_song_only",
            "in_security_assumptions": False,
            "note": "Sau §G.2, guest tự chứng minh phủ đầy đủ. Watchtower chết thì không ai mất tiền.",
        }

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")


if __name__ == "__main__":
    main()
