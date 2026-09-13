#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
 E2E THẬT  ·  sector thật → mạch thật → DA thật → phán quyết thật
═══════════════════════════════════════════════════════════════════════════════

 Chạy:

     python3 scripts/e2e_real.py                      # DA trong bộ nhớ
     ENGRAM_DA=celestia CELESTIA_LOCAL_DEVNET=1 \\
     CELESTIA_RPC=http://127.0.0.1:46658 \\
         python3 scripts/e2e_real.py                  # DA Celestia thật

 ── ĐƯỜNG ĐI, VÀ CÁI GÌ THẬT Ở TỪNG BƯỚC ────────────────────────────────────

   ① ghi sector ra đĩa                    THẬT   byte thật, đọc lại được
   ② niêm phong + Nova + nén Spartan      THẬT   mạch BN254, đo trên máy này
   ③ đăng bằng chứng lên DA               THẬT   đúng 13.776 byte
   ④ worker đọc TỪ DA rồi verify          THẬT   verify byte đọc về, không phải
                                                 byte trên đĩa của nút
   ⑤ nút gian: đục lỗ sector rồi làm lại  THẬT   sealed_root đổi → verify false
   ⑥ gói SP1 + Groth16 + EVM              MOCK   SP1 chỉ execute được, prove hết
                                                 bộ nhớ ở 35 GB

 Bước ⑥ là chỗ duy nhất còn mock trong chuỗi này, và nó có nhãn ở mọi nơi.
═══════════════════════════════════════════════════════════════════════════════
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("common", "provider", "worker", "aggregator", "orchestrator"):
    sys.path.insert(0, str(ROOT / pkg / "src"))

from engram_common.blob import BlobHeader, BlobKind, build_namespace  # noqa: E402
from engram_common.crypto import keccak  # noqa: E402
from engram_common.da import make_da  # noqa: E402
from provider import rust_bridge  # noqa: E402
from provider.sector import Sector  # noqa: E402

# Kết quả ghi vào <gốc repo>/results, KHÔNG vào /tmp.
#
# Bản trước để mọi thứ trong một thư mục tạm, nên chạy xong là mất — vừa không
# so được hai lần chạy, vừa không có gì để nộp kèm bài. Bằng chứng 13.776 byte
# là artifact đáng giữ nhất của cả chuỗi.
RESULTS = Path(os.environ.get("RESULTS_DIR", ROOT / "results"))

N_CHUNKS = int(os.environ.get("ENGRAM_CHUNKS", "16"))
N_CHALLENGES = int(os.environ.get("ENGRAM_CHALLENGES", "3"))
CHAIN_ID = 0x00AA36A7


def line(ch="─"):
    print(ch * 78)


def main() -> int:
    if not rust_bridge.available():
        print("Chưa build mạch Rust. Chạy:")
        print("    cd circuit && cargo build --release -p prover --bin engram_prove")
        print("    cd circuit && cargo build --release -p prover --bin engram_verify")
        return 2

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = RESULTS / f"e2e-{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    da = make_da()
    kind = os.environ.get("ENGRAM_DA", "memory")
    print(f"Tầng DA: {kind}   ·   sector {N_CHUNKS} chunk   ·   {N_CHALLENGES} thách thức")
    line()

    # ── ① sector THẬT ──────────────────────────────────────────────────────
    deal_id = keccak(b"DEAL", b"\x01")
    provider_id = keccak(b"PROVIDER", b"\x01")[:20]
    celestia_addr = keccak(b"CELESTIA", b"\x01")[:20]
    sec = Sector.create(work / "sectors", deal_id, N_CHUNKS)
    print(f"① sector trên đĩa      {sec.on_disk_bytes:>10,} byte   {sec.path.name}")

    # ── ② niêm phong + chứng minh THẬT ─────────────────────────────────────
    t0 = time.time()
    art = rust_bridge.prove(
        sector_path=sec.path, out_dir=work / "proof",
        n_chunks=N_CHUNKS, challenges=N_CHALLENGES,
        replica=deal_id.hex()[:16], beacon="engram-beacon-000",
    )
    print(f"② niêm phong           {art.seal_ms:>10,.1f} ms")
    print(f"   Nova setup          {art.setup_ms:>10,.1f} ms")
    print(f"   fold + nén Spartan  {art.prove_ms:>10,.1f} ms")
    print(f"   bằng chứng          {art.proof_bytes:>10,} byte")
    print(f"   sealed_root         {art.sealed_root}")
    print(f"   thách thức j_i      {art.challenges}")

    # ── ③ đăng lên DA ──────────────────────────────────────────────────────
    ns = build_namespace(BlobKind.BUNDLE, CHAIN_ID, 0)
    hdr = BlobHeader(BlobKind.BUNDLE, 1_000_000, 0, provider_id, deal_id,
                     art.proof_bytes)
    h = da.submit(ns, hdr, art.proof, celestia_addr)
    print(f"③ đăng lên DA          chiều cao {h}   namespace {ns.hex()[:16]}…")

    # ── ④ worker đọc TỪ DA rồi verify ──────────────────────────────────────
    blobs = da.read(ns, h, h + 1)

    # Với backend Celestia, signer do ĐỒNG THUẬN điền bằng khoá của node, không
    # phải giá trị ta truyền vào. Thử truyền giá trị khác thì node từ chối:
    #   "blob signer … does not match MsgPayForBlobs signer … invalid blob signer"
    # Đó chính là tính chất §J.2.1 dựa vào. Nên ở đây lấy signer THẬT từ blob
    # đọc về, đúng như nút sẽ phải đăng ký ở `registerProvider`.
    if kind == "celestia" and blobs:
        that = blobs[0].signer
        print(f"   signer do đồng thuận điền: {that.hex()}")
        if that != celestia_addr:
            print(f"   (ta khai {celestia_addr.hex()} — node ghi đè, ĐÚNG như thiết kế)")
        celestia_addr = that

    mine = [b for b in blobs if b.signer == celestia_addr]
    print(f"④ worker đọc được      {len(blobs)} blob, {len(mine)} qua bộ lọc signer")
    got = mine[0].payload
    print(f"   byte đọc về khớp?   {got == art.proof}")
    v = rust_bridge.verify(art.out_dir, art.n_steps, proof_override=got)
    print(f"   VERIFY              {'PASS' if v['verify_ok'] else 'FAIL'}"
          f"   {v.get('verify_ms', 0):,.1f} ms")

    # ── ⑤ nút gian: đục lỗ THẬT rồi chứng minh lại ─────────────────────────
    line()
    n = sec.lose_fraction(0.25)
    print(f"⑤ đục lỗ {n} chunk trên đĩa, rồi niêm phong và chứng minh lại")
    art2 = rust_bridge.prove(
        sector_path=sec.path, out_dir=work / "proof2",
        n_chunks=N_CHUNKS, challenges=N_CHALLENGES,
        replica=deal_id.hex()[:16], beacon="engram-beacon-000",
    )
    doi = art2.sealed_root != art.sealed_root
    print(f"   sealed_root đổi?    {doi}")
    print(f"   {art.sealed_root}")
    print(f"   {art2.sealed_root}")

    # Bằng chứng MỚI hợp lệ với sector MỚI, nhưng KHÔNG khớp cam kết cũ.
    # Đây đúng là cách hệ bắt nút mất dữ liệu: không phải bằng một cờ, mà bằng
    # việc gốc niêm phong đã cam kết on-chain không còn khớp.
    v2 = rust_bridge.verify(art.out_dir, art.n_steps, proof_override=art2.proof)
    print(f"   verify proof MỚI với vk/z0 CŨ → "
          f"{'PASS' if v2['verify_ok'] else 'FAIL'}  ← phải là FAIL")

    # ── ⑥ phần còn mock ────────────────────────────────────────────────────
    line()
    print("⑥ SP1 wrap + Groth16 + quyết toán EVM:  MOCK")
    print("   SP1 chỉ execute được; prove hết bộ nhớ ở 35 GB. Xem HE_THONG_THAT.md")
    line()
    print(f"Tổng thời gian chuỗi thật: {time.time() - t0:,.1f} giây")

    ok = v["verify_ok"] and doi and not v2["verify_ok"]

    # ── LƯU KẾT QUẢ ────────────────────────────────────────────────────────
    row = {
        "timestamp": stamp,
        "da_backend": kind,
        "n_chunks": N_CHUNKS,
        "n_challenges": N_CHALLENGES,
        "sector_bytes": sec.on_disk_bytes,
        "seal_ms": round(art.seal_ms, 3),
        "setup_ms": round(art.setup_ms, 3),
        "prove_ms": round(art.prove_ms, 3),
        "verify_ms": round(v.get("verify_ms", 0), 3),
        "proof_bytes": art.proof_bytes,
        "vk_bytes": (art.out_dir / "vk.bin").stat().st_size,
        "sealed_root": art.sealed_root,
        "challenges": str(art.challenges),
        "verify_tu_DA": v["verify_ok"],
        "mat_du_lieu_doi_vet": doi,
        "proof_moi_bi_tu_choi": not v2["verify_ok"],
        "ket_qua": "DAT" if ok else "KHONG_DAT",
        "tong_giay": round(time.time() - t0, 1),
    }
    (work / "ket_qua.json").write_text(
        json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # CSV tích luỹ: mỗi lần chạy một dòng, để so được nhiều cấu hình
    csv_path = RESULTS / "e2e_real.csv"
    moi = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if moi:
            w.writeheader()
        w.writerow(row)

    print(f"\nKẾT QUẢ: {'ĐẠT' if ok else 'KHÔNG ĐẠT'}")
    print(f"  → {work}/            proof.bin, vk.bin, z0.bin, ket_qua.json")
    print(f"  → {csv_path}   (một dòng mỗi lần chạy)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
