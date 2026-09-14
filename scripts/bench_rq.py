#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
 bench_rq.py — số liệu cho RQ2 và RQ3, xuất ra CSV
═══════════════════════════════════════════════════════════════════════════════

 Chạy:  python3 scripts/bench_rq.py [--out results]

 Sinh ba tệp:

     results/rq2_total_cost.csv    tổng chi phí theo N, tách ba vế
     results/rq3_grid.csv          lưới (N, S_ns, phần cứng) → có lọt ngân sách
     results/rq_provenance.csv     mỗi con số đến từ đâu: ĐO / MÔ HÌNH / NGOẠI SUY

 ── VÌ SAO CẦN TỆP THỨ BA ───────────────────────────────────────────────────

 Thầy yêu cầu ở P0.9: phân biệt measured / modelled / extrapolated, và không
 gom tất cả thành "end-to-end scalability". Nếu một kết quả ở N = 10.000 chỉ là
 sizing thì phải gọi là sizing.

 Nên script này KHÔNG chỉ in số. Mỗi cột trong hai tệp đầu có một dòng tương
 ứng trong `rq_provenance.csv` nói nó thuộc loại nào và nguồn ở đâu. Người đọc
 bảng không phải đoán.

 ── CÁI SCRIPT NÀY KHÔNG LÀM ────────────────────────────────────────────────

 Nó KHÔNG đo gas: gas đo bằng Foundry, `forge test --match-contract Baselines`.
 Ở đây gas là hằng số đọc từ `constants.py`, và nếu hợp đồng đổi thì phải cập
 nhật hằng số trước khi tin bảng này.

 Nó KHÔNG đo độ trễ DA: chỉ đo được trên devnet, không mô hình được. Để thành
 tham số đầu vào `--da-latency-s` và ghi rõ là chưa đo.
═══════════════════════════════════════════════════════════════════════════════
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("common", "worker"):
    sys.path.insert(0, str(ROOT / pkg / "src"))

from engram_common import constants as C  # noqa: E402
from engram_common.blob import pfb_fee_usd  # noqa: E402
from engram_common.costs import shard_cycles  # noqa: E402
from worker.lottery import cooldown_deadlines, required_workers  # noqa: E402

# ── Giá quy đổi. ĐỀU LÀ GIẢ ĐỊNH, đổi bằng cờ dòng lệnh ────────────────────
ETH_USD = 3000.0
GWEI = 20.0          # giá gas L2 giả định
TIA_USD = 0.65

# Thông lượng prover, chu kỳ mỗi giây. Điểm neo thật duy nhất hiện có là lần
# chạy `make e2e-real` trên máy 1 vCPU; ba mức dưới là để quét trục phần cứng.
PROVER_THROUGHPUT = {
    "1 nhân (neo đo được)": 17e6,
    "16 nhân": 200e6,
    "64 nhân": 700e6,
}


def gas_usd(gas: int, gwei: float = GWEI, eth: float = ETH_USD) -> float:
    return gas * gwei * 1e-9 * eth


# ═══════════════════════════════════════════════════════════════════════════
# RQ2 — khi nào giảm TỔNG chi phí, không chỉ giảm gas
# ═══════════════════════════════════════════════════════════════════════════


def _noi_suy(bang: dict, n: int) -> int:
    """Nội suy/ngoại suy tuyến tính từ các điểm ĐO của Foundry.

    Bảng đo ở N = 1, 2, 5, 10, 20. Ngoài dải đó thì ngoại suy theo độ dốc của
    hai điểm cuối — và `rq_provenance.csv` gọi đúng tên nó là NGOẠI SUY.
    """
    xs = sorted(bang)
    if n in bang:
        return sum(bang[n])
    if n < xs[0]:
        return int(sum(bang[xs[0]]) * n / xs[0])
    if n > xs[-1]:
        a, b = xs[-2], xs[-1]
        doc = (sum(bang[b]) - sum(bang[a])) / (b - a)
        return int(sum(bang[b]) + doc * (n - b))
    for a, b in zip(xs, xs[1:]):
        if a <= n <= b:
            doc = (sum(bang[b]) - sum(bang[a])) / (b - a)
            return int(sum(bang[a]) + doc * (n - a))
    raise ValueError(n)


def rq2_rows(n_list, sha_cycles: int, throughput: float, prover_usd_h: float):
    """Ba vế cộng lại, theo từng cỡ lô.

    Vế nào cũng phải có, vì RQ2 hỏi TỔNG. Bài hiện mạnh ở vế gas và yếu ở hai
    vế kia, nên bảng này là chỗ lộ ra điều đó.
    """
    rows = []
    for n in n_list:
        # ── vế 1: gas on-chain ─────────────────────────────────────────────
        #
        # [SỬA] Dùng SỐ ĐO của Foundry qua `C.BASELINE_GAS`, không tự tính lại.
        #
        # Bản trước tính B1 = N·(21.000 + 13.776×16) = 241.416 ở N=1, tức CHỈ
        # tính intrinsic và bỏ hết execution. Foundry đo được 242.760 + 312.406
        # = 555.166 — gấp 2,3 lần. Hệ quả: bảng này báo Engram đắt hơn B1 ở N=1
        # và có điểm giao ở N=2–3, trong khi số ĐO cho thấy Engram rẻ hơn B1
        # NGAY TỪ N=1 và KHÔNG có điểm giao nào.
        #
        # Hai nguồn số cho hai kết luận trái ngược, và nguồn sai là nguồn tự
        # tính. Giờ nội suy tuyến tính từ điểm đo, không phát minh công thức.
        eng_gas = C.COMMIT_EPOCH_GAS                      # KHÔNG đổi theo N
        b1_gas = _noi_suy(C.BASELINE_GAS["B1"], n)
        b3_gas = _noi_suy(C.BASELINE_GAS["B3"], n)

        # ── vế 2: phí DA ───────────────────────────────────────────────────
        # Cả hai thiết kế đều phải đăng bundle lên DA, nên vế này KHÔNG phải
        # chỗ Engram thắng. Đưa vào vì RQ2 hỏi tổng.
        da_usd = n * pfb_fee_usd(C.BUNDLE_SIZE_BYTES + 74, TIA_USD)

        # ── vế 3: proving ──────────────────────────────────────────────────
        cyc = shard_cycles(n, sha_cycles)
        prove_s = cyc / throughput
        prove_usd = prove_s / 3600 * prover_usd_h

        rows.append({
            "N": n,
            "engram_gas": eng_gas,
            "b1_gas": b1_gas,
            "b3_gas": b3_gas,
            "engram_gas_usd": round(gas_usd(eng_gas), 6),
            "b1_gas_usd": round(gas_usd(b1_gas), 6),
            "b3_gas_usd": round(gas_usd(b3_gas), 6),
            "da_usd": round(da_usd, 6),
            "prove_cycles_e9": round(cyc / 1e9, 2),
            "prove_seconds": round(prove_s, 1),
            "prove_usd": round(prove_usd, 6),
            # TỔNG: đây là cột mà bài hiện chưa có ở đâu cả
            "engram_total_usd": round(gas_usd(eng_gas) + da_usd + prove_usd, 6),
            "b1_total_usd": round(gas_usd(b1_gas) + da_usd, 6),
            "b3_total_usd": round(gas_usd(b3_gas) + da_usd, 6),
        })
    return rows


def crossovers(rows):
    """Điểm giao theo GAS và theo TỔNG — hai con số khác nhau.

    Bài hiện chỉ nói điểm giao theo gas. Nếu hai con số lệch nhau thì đó là
    một kết quả đáng báo cáo, vì nó đúng là câu hỏi của RQ2.
    """
    out = {}
    for base in ("b1", "b3"):
        for metric in ("gas_usd", "total_usd"):
            prev = None
            for r in rows:
                cheaper = r[f"engram_{metric}"] < r[f"{base}_{metric}"]
                if prev is not None and cheaper and not prev[0]:
                    out[f"{base}_{metric}"] = f"giữa N={prev[1]} và N={r['N']}"
                    break
                prev = (cheaper, r["N"])
            else:
                out[f"{base}_{metric}"] = "không giao trong dải đã quét"
    return out


# ═══════════════════════════════════════════════════════════════════════════
# RQ3 — điểm vận hành giữa năm chiều
# ═══════════════════════════════════════════════════════════════════════════

# Ngân sách THẬT, không phải L·t_epoch.
#
# Aggregator không gom được cho tới khi ChildProof CUỐI CÙNG về, mà cửa sổ
# deadline 47 chỉ đóng ở 14.305 block = 23,84 giờ trong epoch. Nên:
#     28.800 − 14.305 = 14.495 block ≈ 24,16 giờ
BUDGET_SECONDS = 14_495 * C.CELESTIA_BLOCK_TIME_S


def rq3_rows(n_list, shard_list, sha_cycles: int, da_latency_s: float):
    """Lưới (N, S_ns, phần cứng) → có lọt ngân sách 24,16 giờ hay không.

    Biến RQ3 từ một mô tả thành một phép kiểm nhị phân: với bộ tham số này, hệ
    có kịp cam kết epoch trước hạn hay không.
    """
    D = C.PROFILE_PRODUCTION.deadlines_per_epoch
    rows = []
    for n in n_list:
        for s_ns in shard_list:
            cells = D * s_ns
            per_cell = max(1, n // cells)
            cyc = shard_cycles(per_cell, sha_cycles)
            for hw, thr in PROVER_THROUGHPUT.items():
                t_worker = cyc / thr
                # Đường tới hạn: worker ô CUỐI, rồi aggregator gom D·S_ns nút.
                # Độ trễ DA cộng vào vì blob phải đọc được trước khi xử lý.
                t_agg = shard_cycles(cells, sha_cycles) / thr
                critical = t_worker + t_agg + da_latency_s
                cd = cooldown_deadlines(t_worker, C.PROFILE_PRODUCTION.deadline_len_blocks
                                        * C.CELESTIA_BLOCK_TIME_S)
                rows.append({
                    "N": n,
                    "S_ns": s_ns,
                    "cells": cells,
                    "deals_per_cell": per_cell,
                    "hardware": hw,
                    "cell_cycles_e9": round(cyc / 1e9, 2),
                    "t_worker_h": round(t_worker / 3600, 2),
                    "t_agg_h": round(t_agg / 3600, 2),
                    "da_latency_s": da_latency_s,
                    "critical_path_h": round(critical / 3600, 2),
                    "budget_h": round(BUDGET_SECONDS / 3600, 2),
                    "lot_ngan_sach": critical <= BUDGET_SECONDS,
                    "cooldown_deadlines": cd,
                    "workers_toi_thieu": required_workers(s_ns, C.WORKER_REDUNDANCY_R, cd),
                    # NFR-05: đừng chia quá nhỏ, kẻo trả f nhiều lần cho ô gần rỗng
                    "nfr05_ok": cells <= n / 20 if n else False,
                })
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# Xuất xứ từng con số
# ═══════════════════════════════════════════════════════════════════════════

PROVENANCE = [
    ("engram_gas", "ĐO", "Foundry, forge test --match-contract Baselines. "
     "Hằng số COMMIT_EPOCH_GAS — cập nhật SAU MỖI lần đổi hợp đồng"),
    ("b1_gas / b3_gas", "ĐO + TÍNH", "quy tắc EIP-2028 16 gas/byte khác 0; "
     "B1 chỉ tính intrinsic nên thiên vị baseline, so sánh là bảo thủ"),
    ("da_usd", "TÍNH", "pfb_gas() theo quy tắc Celestia; ba đầu vào là GIẢ ĐỊNH: "
     "phí cố định 65.000, giá gas 0,002 utia, giá TIA 0,65 $. CHƯA đo trên devnet"),
    ("prove_cycles_e9", "ĐO rồi NGOẠI SUY",
     "f + m·N, hồi quy trên BỐN điểm N = 1, 2, 4, 8 bằng SP1 execute "
     "(13/9/2026, sp1-sdk 6.4.0). R² = 1,00000000, sai số từng điểm < 0,0001 %. "
     "Kiểm ngoài mẫu tại N = 5: sai số 3e-5. Mọi N > 8 là NGOẠI SUY"),
    ("prove_seconds", "MÔ HÌNH", "chu kỳ chia thông lượng prover giả định. "
     "Điểm neo thật duy nhất: 1 vCPU trong make e2e-real"),
    ("prove_usd", "MÔ HÌNH", "thời gian nhân giá thuê máy giả định"),
    ("cell_cycles_e9", "ĐO rồi NGOẠI SUY", "như prove_cycles_e9 — đo tới N = 8"),
    ("t_worker_h / t_agg_h", "MÔ HÌNH", "chu kỳ chia thông lượng"),
    ("da_latency_s", "CHƯA ĐO", "chỉ đo được trên devnet Celestia; tham số đầu vào"),
    ("budget_h", "SUY TỪ LỊCH", "28.800 − 14.305 block. Đây là ĐÍNH CHÍNH: "
     "Eq.(2) gợi ý 48 giờ, ngân sách thật là 24,16 giờ vì cửa sổ cuối đóng ở 23,84 giờ"),
    ("workers_toi_thieu", "SUY TỪ CÔNG THỨC", "S_ns · r · (cooldown+1)"),
    ("13.776 byte, 4.738.776 byte", "ĐO", "make e2e-real, mạch Nova/Spartan thật"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    # Neo vào GỐC REPO, không phải thư mục hiện tại. Chạy từ scripts/ hay từ
    # chỗ khác đều ghi về cùng một nơi — nếu không, kết quả rải rác mỗi lần
    # một chỗ và không ai biết bảng nào mới.
    ap.add_argument("--out", default=str(ROOT / "results"))
    ap.add_argument("--sha-cycles", type=int, default=5_000,
                    help="c_sha — CHƯA ĐO, xem [MỞ C2-b]")
    ap.add_argument("--da-latency-s", type=float, default=0.0,
                    help="độ trễ DA, CHƯA ĐO — đặt tay hoặc đo trên devnet")
    ap.add_argument("--prover-usd-h", type=float, default=0.40)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    n_list = [1, 2, 3, 5, 10, 20, 50, 100, 500, 1_000, 10_000]
    rows2 = rq2_rows(n_list, a.sha_cycles,
                     PROVER_THROUGHPUT["16 nhân"], a.prover_usd_h)
    _write(out / "rq2_total_cost.csv", rows2)

    rows3 = rq3_rows([1_000, 10_000], [1, 2, 4, 8, 16, 32],
                     a.sha_cycles, a.da_latency_s)
    _write(out / "rq3_grid.csv", rows3)

    _write(out / "rq_provenance.csv",
           [{"cot": c, "loai": k, "nguon": s} for c, k, s in PROVENANCE])

    # ── in tóm tắt ─────────────────────────────────────────────────────────
    print("── RQ2 · điểm giao ───────────────────────────────────────────")
    for k, v in crossovers(rows2).items():
        print(f"  {k:<22} {v}")
    print("\n  Nếu hai con số 'gas_usd' và 'total_usd' LỆCH nhau thì đó là kết")
    print("  quả đáng báo cáo — RQ2 hỏi tổng, bài hiện chỉ nói theo gas.")

    print("\n── RQ3 · cấu hình lọt ngân sách 24,16 giờ ────────────────────")
    ok = [r for r in rows3 if r["lot_ngan_sach"] and r["nfr05_ok"]]
    if not ok:
        print("  KHÔNG cấu hình nào lọt. Kiểm lại thông lượng prover giả định.")
    for r in ok[:8]:
        print(f"  N={r['N']:>6} S_ns={r['S_ns']:>3} {r['hardware']:<22}"
              f" tới hạn {r['critical_path_h']:>6.2f}h  worker≥{r['workers_toi_thieu']}")

    print(f"\n  → {out.resolve()}/rq2_total_cost.csv")
    print(f"  → {out.resolve()}/rq3_grid.csv")
    print(f"  → {out.resolve()}/rq_provenance.csv")
    print("\nĐọc rq_provenance.csv TRƯỚC khi trích số nào vào bài.")
    return 0


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    sys.exit(main())
