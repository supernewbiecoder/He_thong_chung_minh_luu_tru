"""
[SPEC §C.2.1] Giao diện HTTP của nút lưu trữ.

    I-01  POST /v1/quote                  khách hỏi giá
          POST /v1/deals/{id}/chunks      khách gửi dữ liệu
          GET  /v1/deals/{id}/status
          GET  /v1/health

Không có endpoint nào nhận bundle hay trả bundle: bundle đi lên Celestia, và
worker tự đi lấy. Đây là điểm khác biệt then chốt — KHÔNG có kênh điểm-điểm nào
để chặn hay kiểm duyệt. [SPEC §A.2.5]
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from engram_common.crypto import merkle_root, poseidon2_stub

from .config import ProviderConfig
from .sealing import derive_replica_id, seal
from .storage import DealStorage, generate_chunk


class QuoteRequest(BaseModel):
    piece_root_hex: str
    piece_size_real: int = Field(gt=0)
    duration_epochs: int = Field(gt=0)


class QuoteResponse(BaseModel):
    provider: str
    price_per_epoch_wei: int
    sealing_fee_wei: int
    # [SPEC §F.1.2] Hạn theo CHIỀU CAO BLOCK, không theo giờ.
    #
    # Hạn theo giờ đồng hồ là điểm đầu tiên đồng hồ cục bộ lọt vào giao thức, và
    # nó vô nghĩa: khách và nút lệch nhau vài giây thì báo giá "còn hạn" với bên
    # này và "hết hạn" với bên kia, mà không bên nào chứng minh được.
    valid_until_eth_height: int
    accepted: bool


class ChunkBatch(BaseModel):
    start_index: int
    chunks_hex: list[str]


def build_app(cfg: ProviderConfig) -> FastAPI:
    app = FastAPI(title=f"engram-provider[{cfg.name}]", version="0.1.0")
    deals: dict[str, DealStorage] = {}
    received: dict[str, list[bytes]] = {}

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {
            "service": "provider",
            "name": cfg.name,
            "chain_mode": cfg.chain_mode,
            "profile": cfg.profile.name,
            "celestia_address": cfg.celestia_address.hex(),
            "deals": len(deals),
        }

    @app.post("/v1/quote", response_model=QuoteResponse)
    def quote(req: QuoteRequest) -> QuoteResponse:
        from engram_common.costs import sealing_fee_wei

        free = cfg.capacity_slots - len(deals)
        return QuoteResponse(
            provider=cfg.name,
            price_per_epoch_wei=10**12,
            sealing_fee_wei=sealing_fee_wei(cfg.sim_chunks_per_deal),
            valid_until_eth_height=0,  # điền bởi chain_client khi chạy thật
            accepted=free > 0,
        )

    @app.post("/v1/deals/{deal_id}/chunks")
    def put_chunks(deal_id: str, batch: ChunkBatch) -> dict[str, Any]:
        """[SPEC UC-02 ①] Khách gửi dữ liệu THEO TỪNG CHUNK.

        Truyền theo chunk chứ không một cục, vì 32 GiB qua mạng cần nối lại
        được, và khách xác minh TỪNG chunk bằng đường Merkle lên piece_root của
        chính mình — không đợi tới cuối mới đối chiếu.
        """
        buf = received.setdefault(deal_id, [])
        if batch.start_index != len(buf):
            raise HTTPException(409, f"chờ chunk {len(buf)}, nhận {batch.start_index}")
        buf.extend(bytes.fromhex(h) for h in batch.chunks_hex)
        return {"received": len(buf)}

    @app.post("/v1/deals/{deal_id}/accept")
    def accept(deal_id: str, piece_root_hex: str, activation_beacon_hex: str) -> dict[str, Any]:
        """[SPEC UC-02 ②] Nút tính lại piece_root. Lệch thì TỪ CHỐI NHẬN.

        Chưa lên chuỗi nên không ai bị phạt — chỉ truyền lại đúng những chunk sai.
        """
        buf = received.get(deal_id, [])
        if not buf:
            raise HTTPException(404, "chưa nhận chunk nào")

        recomputed = merkle_root([poseidon2_stub(c) for c in buf], hasher=poseidon2_stub)
        if recomputed.hex() != piece_root_hex:
            raise HTTPException(422, "piece_root lệch — dữ liệu hỏng trên đường truyền")

        did = bytes.fromhex(deal_id)
        replica = derive_replica_id(
            cfg.celestia_address, did, recomputed, bytes.fromhex(activation_beacon_hex)
        )
        res = seal(buf, replica)

        st = DealStorage(deal_id=did, n_chunks=len(buf))
        st.r_values, st.s_chain, st.sealed_root = res.r_values, res.s_chain, res.sealed_root
        deals[deal_id] = st
        received.pop(deal_id, None)  # dữ liệu thô sinh lại được, không giữ trong RAM

        return {
            "sealed_root": res.sealed_root.hex(),
            "replica_id": replica.hex(),
            # Thời gian MÔ HÌNH HOÁ. Ở quy mô thật (8.388.608 chunk) là 1,26 giờ,
            # và thêm nhân CPU không rút ngắn được — 0 % song song hoá được.
            "seal_seconds_modelled": round(res.seconds_modelled, 3),
            "seal_form_bytes": st.seal_form_bytes,
        }

    @app.get("/v1/deals/{deal_id}/status")
    def status(deal_id: str) -> dict[str, Any]:
        st = deals.get(deal_id)
        if st is None:
            raise HTTPException(404, "không có hợp đồng này")
        return {
            "deal_id": deal_id,
            "n_chunks": st.n_chunks,
            "sealed_root": st.sealed_root.hex(),
            "lost_chunks": len(st.lost_indices),
            "seal_form_bytes": st.seal_form_bytes,
        }

    @app.post("/v1/admin/lose")
    def admin_lose(deal_id: str, fraction: float) -> dict[str, Any]:
        """CHỈ DÙNG KHI MÔ PHỎNG — kịch bản KB-05, nút mất một ổ cứng."""
        st = deals.get(deal_id)
        if st is None:
            raise HTTPException(404, "không có hợp đồng này")
        return {"lost": st.lose_fraction(fraction)}

    return app
