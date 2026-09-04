"""
CHỈ DÙNG KHI MÔ PHỎNG — dựng kịch bản, thu số liệu.

    python -m orchestrator --deals 20 --epochs 3 --shards 2

[CHỐT C2-b] Quét ba giá trị c_sha thay vì chốt một, biến ẩn số thành phân tích
độ nhạy — và cho biết phép đo thật cần rơi dưới mức nào.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from engram_common.constants import SHA256_SWEEP
from engram_common.costs import (
    attacker_floor_seconds, capacity_bound_cores, coverage_cost_ratio,
    regen_economics, seal_seconds,
)

from .harness import SimNetwork
from .scenarios import run_epoch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deals", type=int, default=int(os.getenv("N_DEALS", 20)))
    ap.add_argument("--epochs", type=int, default=int(os.getenv("N_EPOCHS", 3)))
    ap.add_argument("--shards", type=int, default=int(os.getenv("N_SHARDS", 2)))
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--out", default=os.getenv("RESULTS_DIR", "results"))
    a = ap.parse_args()

    print(f"═══ Engram · mô phỏng · {a.deals} hợp đồng · {a.shards} mảnh · {a.epochs} epoch ═══\n")

    rows = []
    for sha in SHA256_SWEEP:
        net = SimNetwork(n_deals=a.deals, n_shards=a.shards,
                         n_workers=a.workers, sha_cycles=sha).build()
        # [CHỐT F3] Hai worker rời mạng giữa chừng — xổ số phải tự lọc ra.
        for w in net.worker_pool[:2]:
            net.dead_workers.add(w.worker_id)
        # KB-05 đường B: nút mất dữ liệu nhưng IM LẶNG về việc đó → FAIL
        if len(net.deals) > 3:
            net.deals[3].lost = True
        # Nút offline hoàn toàn → ABSENT, và ABSENT ở đây là kết luận ĐƯỢC
        # CHỨNG MINH nhờ phủ đầy đủ §G.2, không phải lời khai của worker.
        if len(net.deals) > 7:
            net.deals[7].offline = True
        # KB-05 đường A: nút mất dữ liệu nhưng TỰ KHAI trước deadline → phạt nhẹ
        if len(net.deals) > 11:
            net.deals[11].lost = True
            net.deals[11].declared = True
        # §J.2.1: kẻ ngoài mạo danh hợp đồng đầu tiên
        target = net.deals[0]

        for e in range(1, a.epochs + 1):
            r = run_epoch(net, e, attack_target=target, n_decoys=5)
            r["sha_cycles"] = sha
            rows.append(r)
            if sha == SHA256_SWEEP[1]:
                print(f"  epoch {e}: PASS={r['n_pass']:>3} FAIL={r['n_fail']:>2} "
                      f"ABSENT={r['n_absent']:>2} · {r['cycles_e9']:>7.1f}e9 chu kỳ · "
                      f"{r['decoys_dropped']} blob mạo danh bị loại · "
                      f"calldata {r['calldata_bytes']} B")

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with (out / "epochs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    print(f"\n── Quét c_sha [CHỐT C2-b] ──")
    for sha in SHA256_SWEEP:
        sub = [r for r in rows if r["sha_cycles"] == sha]
        avg = sum(r["cycles_e9"] for r in sub) / len(sub)
        print(f"  c_sha={sha:>6,}: {avg:>8.1f}e9 chu kỳ/epoch · "
              f"phủ đầy đủ = {coverage_cost_ratio(sha)*100:5.2f}% một bundle")

    print(f"\n── Xoay vòng và tính sống ──")
    from worker.lottery import adaptive_cap_ratio, cooldown_deadlines, required_workers
    cd = cooldown_deadlines(3.1 * 3600, 300 * 6.0)
    print(f"  t_worker ~3,1 giờ · deadline 30 phút  → nghỉ {cd} deadline")
    print(f"  cần ít nhất {required_workers(a.shards, 2, cd)} worker cho {a.shards} mảnh "
          f"({required_workers(16, 2, cd)} nếu 16 mảnh)")
    print(f"  trần thích ứng ở {a.workers} worker    : {adaptive_cap_ratio(a.workers)*100:.1f}%")
    print(f"  worker bị đình chỉ trong lần chạy    : {len(net.dead_workers)} rời mạng")

    print(f"\n── Đối chiếu với đặc tả ──")
    print(f"  t_seal (§E.1.4 ghi 1,28 giờ)      : {seal_seconds()/3600:.2f} giờ")
    print(f"  sàn kẻ gian (§E.1.4 ghi 38,4 phút): {attacker_floor_seconds()/60:.1f} phút")
    for cpu in (0.005, 0.04):
        print(f"  biên dựng lại ở {cpu:.3f} $/giờ CPU  : {regen_economics(cpu_usd_per_hour=cpu).margin:>9,.0f}×")
    print(f"  gian 1.000 hợp đồng cần            : {capacity_bound_cores(1000):.1f} nhân 24/24")
    # In đường dẫn TUYỆT ĐỐI. Đường dẫn tương đối làm người dùng tưởng tệp nằm
    # ở thư mục hiện tại, trong khi ở container nó nằm ở /app — và mất khi
    # container thoát nếu không mount đúng chỗ.
    print(f"\n  → {(out / 'epochs.csv').resolve()}")


if __name__ == "__main__":
    main()
