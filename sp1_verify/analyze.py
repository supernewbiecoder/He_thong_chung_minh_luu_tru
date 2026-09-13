#!/usr/bin/env python3
"""
Phân tích results.jsonl → bảng cho paper + CSV để vẽ biểu đồ.

Dùng (ở MÁY BẠN, sau khi scp results về):
    python3 analyze.py results/results.jsonl
    python3 analyze.py results/results.jsonl --outdir analysis
    python3 analyze.py results/results.jsonl --tree-height 23      # chỉ config production
    python3 analyze.py results/results.jsonl --run-id 20260727_101500_42

Sinh ra:
    analysis/table_rq1_calldata.md   — RQ1: DA tiết kiệm calldata bao nhiêu
    analysis/table_rq2_constant.md   — RQ2: chi phí EVM có hằng số không
    analysis/table_rq3_overhead.md   — RQ3: đánh đổi off-chain (có cả peak RAM)
    analysis/table_control_distinct.md — điểm đối chứng bundle phân biệt vs bản sao
    analysis/data.csv                — dữ liệu phẳng, mở bằng Excel/Sheets để vẽ

── SỬA SO VỚI BẢN TRƯỚC ──
 1. Mở gói `cfg` lồng (do host ghi từ meta.json) → tree_height/sector_size thành cột.
 2. TÁCH BẢNG THEO tree_height. Trước đây một điểm đo ở sector 64KB và một điểm ở 32GB
    sẽ nằm chung một bảng, cùng cột "Batch", không cách nào phân biệt.
 3. KHỬ TRÙNG: cùng (mode,batch,challenges,tree_height,distinct) thì giữ dòng ts mới
    nhất và BÁO số dòng bị gộp. Trước đây smoke + phase 1b sinh hai dòng y hệt và bảng
    âm thầm lấy một dòng bất kỳ.
 4. Gas verify Groth16: 250k → 270k (docs Succinct), và cho phép đổi bằng --gas-verify.
 5. Thêm cột peak RSS (RQ3 trước đây không có số RAM nào).
"""
import argparse
import csv
import json
import os
import statistics
import sys
from collections import defaultdict

# Chi phí gas EVM (ước lượng — chỉnh theo số đo thật từ Foundry)
GAS_PER_CALLDATA_BYTE_NONZERO = 16    # EIP-2028
GAS_GROTH16_VERIFY_DEFAULT = 270_000  # docs Succinct: Groth16 ~260B, verify ~270k gas
GAS_BASE_TX = 21_000

# Khoá xác định một "điểm đo" duy nhất.
DEDUP_KEY = ("mode", "batch", "challenges", "tree_height", "distinct")


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  ⚠️  bỏ qua dòng {ln} không phải JSON hợp lệ", file=sys.stderr)
    return rows


def flatten(rows):
    """Đưa cfg.* lên cấp 1 để dùng như cột thường. cfg do bundle_gen ghi vào meta.json."""
    out = []
    for r in rows:
        r = dict(r)
        cfg = r.pop("cfg", None)
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                # cfg.challenges trùng tên với cột challenges của host → giữ của host
                if k not in r:
                    r[k] = v
        r.setdefault("distinct", False)
        out.append(r)
    return out


def dedup(rows):
    """Giữ dòng ts mới nhất cho mỗi điểm đo; trả về (rows_sạch, số_dòng_bị_gộp)."""
    best = {}
    order = []
    for i, r in enumerate(rows):
        if r.get("mode") not in ("execute", "prove"):
            continue
        if r.get("mode") in ("execute", "prove") and r.get("ok") is not True:
            continue
        key = tuple(r.get(k) for k in DEDUP_KEY)
        prev = best.get(key)
        if prev is None:
            best[key] = (i, r)
            order.append(key)
        else:
            # ts lớn hơn thắng; ts bằng nhau thì dòng sau thắng (chạy lại là bản sửa)
            if r.get("ts", 0) >= prev[1].get("ts", 0):
                best[key] = (i, r)
    eligible = sum(
        1 for r in rows
        if r.get("mode") == "prove" and r.get("ok") is True
        or (r.get("mode") == "execute" and r.get("ok") is True)
    )
    collapsed = eligible - len(best)
    return [best[k][1] for k in order], collapsed


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def fmt_bytes(b):
    b = b or 0
    if b >= 1024 * 1024:
        return f"{b/1024/1024:.2f} MB"
    if b >= 1024:
        return f"{b/1024:.1f} KB"
    return f"{b} B"


def fmt_rss(kib):
    kib = kib or 0
    if kib >= 1048576:
        return f"{kib/1048576:.2f} GiB"
    if kib >= 1024:
        return f"{kib/1024:.0f} MiB"
    return f"{kib} KiB"


def fmt_gib(value):
    return f"{(value or 0) / 1073741824:.2f} GiB"


def write(outdir, name, content):
    with open(os.path.join(outdir, name), "w", encoding="utf-8") as f:
        f.write(content)


def write_execute_replicates(rows, outdir):
    """Giữ TOÀN BỘ replicate hợp lệ thay vì chỉ lấy dòng mới nhất.

    Cycles/prover-gas phải tất định với cùng ELF+input; thời gian và RAM cần
    mean/std/max qua nhiều container. Chỉ nhận dòng `ok=true`, vì một execute
    không commit đủ public values không được dùng làm số liệu paper.
    """
    valid = [
        r for r in rows
        if r.get("mode") == "execute"
        and r.get("ok") is True
        and r.get("num_verified") == r.get("batch")
    ]
    invalid = [r for r in rows if r.get("mode") == "execute" and r not in valid]
    groups = defaultdict(list)
    for r in valid:
        key = (
            r.get("tree_height"), r.get("challenges"), r.get("batch"),
            bool(r.get("distinct", False)), r.get("phase", "?"),
        )
        groups[key].append(r)

    csv_path = os.path.join(outdir, "execute_replicates.csv")
    fields = [
        "tree_height", "challenges", "batch", "distinct", "phase", "n",
        "cycles_mean", "cycles_min", "cycles_max", "prover_gas_mean",
        "execute_s_mean", "execute_s_std", "throughput_mcycles_s_mean",
        "peak_rss_kib_mean", "cgroup_memory_peak_bytes_mean",
        "cgroup_memory_peak_bytes_max",
    ]
    summary_rows = []
    for key, grp in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        cycles = [int(r.get("cycles", 0)) for r in grp]
        gas = [int(r.get("prover_gas", 0)) for r in grp]
        times = [float(r.get("execute_s", 0)) for r in grp]
        throughputs = [float(r.get("throughput_mcycles_s", 0)) for r in grp]
        rss = [int(r.get("peak_rss_kib", 0)) for r in grp]
        cg_peak = [int(r.get("cgroup_memory_peak_bytes", 0)) for r in grp]
        row = {
            "tree_height": key[0], "challenges": key[1], "batch": key[2],
            "distinct": key[3], "phase": key[4], "n": len(grp),
            "cycles_mean": round(statistics.fmean(cycles), 2),
            "cycles_min": min(cycles), "cycles_max": max(cycles),
            "prover_gas_mean": round(statistics.fmean(gas), 2),
            "execute_s_mean": round(statistics.fmean(times), 3),
            "execute_s_std": round(statistics.stdev(times), 3) if len(times) > 1 else 0.0,
            "throughput_mcycles_s_mean": round(statistics.fmean(throughputs), 4),
            "peak_rss_kib_mean": round(statistics.fmean(rss), 2),
            "cgroup_memory_peak_bytes_mean": round(statistics.fmean(cg_peak), 2),
            "cgroup_memory_peak_bytes_max": max(cg_peak),
        }
        summary_rows.append(row)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    table_rows = []
    for r in summary_rows:
        deterministic = "✅" if r["cycles_min"] == r["cycles_max"] else "⚠️"
        table_rows.append([
            r["tree_height"], r["challenges"], r["batch"], r["distinct"],
            r["phase"], r["n"], f"{r['cycles_mean']:,.0f}",
            f"{r['prover_gas_mean']:,.0f}",
            f"{r['execute_s_mean']:.2f} ± {r['execute_s_std']:.2f}",
            fmt_gib(r["cgroup_memory_peak_bytes_mean"]),
            fmt_gib(r["cgroup_memory_peak_bytes_max"]), deterministic,
        ])
    body = md_table(
        ["h", "Challenges", "Batch", "Distinct", "Phase", "n", "Cycles mean",
         "Prover gas mean", "Execute s (mean ± sd)", "Cgroup RAM mean",
         "Cgroup RAM max", "Cycles stable"],
        table_rows,
    ) if table_rows else "_Chưa có dòng execute hợp lệ (`ok=true`)._"
    write(
        outdir,
        "table_execute_replicates.md",
        "# SP1 execute — replicate thực đo\n\n"
        f"- Dòng execute hợp lệ: **{len(valid)}**\n"
        f"- Dòng execute bị loại: **{len(invalid)}**\n"
        "- Điều kiện hợp lệ: `ok=true` và `num_verified == batch`.\n\n"
        + body + "\n",
    )
    print(f"✅ {csv_path}")
    print(f"✅ {outdir}/table_execute_replicates.md")


def gas_pair(da, evm, gas_verify):
    baseline = GAS_BASE_TX + (da or 0) * GAS_PER_CALLDATA_BYTE_NONZERO
    ours = GAS_BASE_TX + (evm or 0) * GAS_PER_CALLDATA_BYTE_NONZERO + gas_verify
    return baseline, ours


def hgroups(rows):
    """Gom theo tree_height — mỗi tree_height là một cấu hình đo KHÁC NHAU."""
    g = defaultdict(list)
    for r in rows:
        g[r.get("tree_height", "?")].append(r)
    return dict(sorted(g.items(), key=lambda kv: (kv[0] == "?", kv[0])))


def analyze(raw, outdir, gas_verify, want_run=None, want_h=None):
    os.makedirs(outdir, exist_ok=True)
    rows = flatten(raw)

    metas = [r for r in rows if r.get("mode") == "run_meta"]
    if metas:
        m = metas[-1]
        print(f"🖥️  Lượt chạy gần nhất: run_id={m.get('run_id')} host={m.get('host')} "
              f"nproc={m.get('nproc')} sp1={m.get('sp1_version')} git={m.get('git_sha')}")
        if len(metas) > 1:
            print(f"   (file này chứa {len(metas)} lượt sweep — dùng --run-id để lọc)")

    if want_run:
        rows = [r for r in rows if r.get("run_id") == want_run]
    if want_h is not None:
        rows = [r for r in rows if r.get("tree_height") == want_h
                or r.get("mode") == "run_meta"]

    write_execute_replicates(rows, outdir)

    measured, collapsed = dedup(rows)
    if collapsed:
        print(f"🧹 Gộp {collapsed} dòng trùng điểm đo (giữ ts mới nhất). "
              f"Khoá: {'+'.join(DEDUP_KEY)}")

    execs = [r for r in measured if r["mode"] == "execute" and r.get("ok") is True]
    proves = [r for r in measured if r["mode"] == "prove" and r.get("ok") is True]
    invalid_proves = [
        r for r in rows
        if r.get("mode") == "prove" and r.get("ok") is not True
    ]
    gens = [r for r in rows if r.get("mode") == "bundle_gen"]
    print(
        f"📥 Sau khử trùng: {len(execs)} execute hợp lệ, {len(proves)} prove hợp lệ, "
        f"{len(invalid_proves)} prove bị loại, {len(gens)} bundle_gen"
    )

    heights = sorted({r.get("tree_height") for r in execs + proves}, key=lambda x: (x is None, x))
    if len(heights) > 1:
        print(f"⚠️  Dữ liệu chứa NHIỀU tree_height: {heights} — các bảng sẽ tách riêng. "
              f"KHÔNG được vẽ chung một đường.")

    # ── CSV phẳng để vẽ biểu đồ ───────────────────────────────────────────
    csv_path = os.path.join(outdir, "data.csv")
    keys = ["mode", "ok", "run_id", "phase", "ts", "tree_height", "num_chunks",
            "sector_size_bytes", "batch", "distinct", "challenges", "cycles",
            "cycles_per_bundle", "prover_gas", "prover_gas_per_bundle",
            "execute_s", "throughput_mcycles_s", "prove_s", "peak_rss_kib",
            "cgroup_memory_current_bytes", "cgroup_memory_peak_bytes",
            "groth16_bytes", "public_values_bytes", "evm_calldata_bytes",
            "one_bundle_bytes", "da_payload_bytes", "gen_s", "seal_s", "fold_s",
            "bundle_bytes", "num_verified", "pv_bytes", "seed"]
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(",".join(keys) + "\n")
        for r in measured + gens:
            f.write(",".join(str(r.get(k, "")) for k in keys) + "\n")
    print(f"✅ {csv_path}")

    # ── RQ1: DA vs calldata ───────────────────────────────────────────────
    if proves:
        parts = []
        for h, grp in hgroups([p for p in proves if not p.get("distinct")]).items():
            rq1 = []
            for p in sorted(grp, key=lambda x: x.get("batch", 0)):
                da, evm = p.get("da_payload_bytes", 0), p.get("evm_calldata_bytes", 0)
                gb, go = gas_pair(da, evm, gas_verify)
                rq1.append([p.get("batch"), fmt_bytes(da), fmt_bytes(evm),
                            f"{(da/evm) if evm else 0:.1f}×",
                            f"{gb:,}", f"{go:,}",
                            f"{gb/go:.2f}×" if go else "—"])
            parts.append(f"## tree_height = {h} "
                         f"(sector {fmt_bytes(grp[0].get('sector_size_bytes', 0))})\n\n"
                         + md_table(["Batch", "Payload (DA)", "Calldata (EVM)", "Giảm",
                                     "Gas baseline A", "Gas Modular-PoSt",
                                     "Tiết kiệm gas"], rq1))
        note = ("\n\n> ⚠️ Gas là ƯỚC LƯỢNG: 16 gas/byte calldata (EIP-2028) + "
                f"{gas_verify:,} gas verify Groth16. CHƯA phải số đo — chưa có contract "
                "EVM trong repo. Thay bằng `forge test --gas-report` khi có.\n"
                "> ⚠️ `da_payload_bytes` ở chế độ nhân bản là phép NHÂN "
                "(one_bundle_bytes × batch), không phải tổng đo từ blob Celestia thật.\n")
        write(outdir, "table_rq1_calldata.md",
              "# RQ1 — DA tiết kiệm on-chain data bao nhiêu?\n\n"
              + "\n\n".join(parts) + note)
        print(f"✅ {outdir}/table_rq1_calldata.md")
    else:
        print("⏭️  Chưa có dữ liệu prove → bỏ qua RQ1 (cần groth16_bytes)")

    # ── RQ2: chi phí EVM có hằng số? ──────────────────────────────────────
    if proves:
        parts = []
        for h, grp in hgroups([p for p in proves if not p.get("distinct")]).items():
            sizes = {p.get("groth16_bytes") for p in grp}
            calldata = {p.get("evm_calldata_bytes") for p in grp}
            if len(grp) < 2:
                verdict = "ℹ️ chỉ có 1 điểm — chưa kết luận được gì về tính hằng số"
            elif len(sizes) == 1 and len(calldata) == 1:
                verdict = "✅ HẰNG SỐ — proof size và calldata không đổi khi batch tăng"
            elif len(sizes) == 1:
                verdict = ("⚠️ proof size hằng số nhưng calldata đổi → public values đổi "
                           "kích thước, kiểm lại struct commit")
            else:
                verdict = "⚠️ proof size THAY ĐỔI giữa các batch — cần kiểm tra lại"
            rq2 = [[p.get("batch"), p.get("groth16_bytes"), p.get("public_values_bytes"),
                    p.get("evm_calldata_bytes"), f"{p.get('prove_s', 0):.1f}s",
                    fmt_rss(p.get("peak_rss_kib"))]
                   for p in sorted(grp, key=lambda x: x.get("batch", 0))]
            parts.append(f"## tree_height = {h}\n\n"
                         + md_table(["Batch", "Groth16 (B)", "Public values (B)",
                                     "EVM calldata (B)", "Prove time", "Peak RSS"], rq2)
                         + f"\n\n**Kết luận:** {verdict}")
        write(outdir, "table_rq2_constant.md",
              "# RQ2 — Chi phí verify on-chain có gần như hằng số?\n\n"
              + "\n\n".join(parts) + "\n")
        print(f"✅ {outdir}/table_rq2_constant.md")

    # ── RQ3: overhead off-chain ───────────────────────────────────────────
    if execs:
        parts = []
        for h, grp in hgroups([e for e in execs if not e.get("distinct")]).items():
            rq3 = [[e.get("challenges"), e.get("batch"),
                    f"{e.get('cycles', 0):,}", f"{e.get('cycles_per_bundle', 0):,}",
                    f"{e.get('execute_s', 0):.1f}s", fmt_rss(e.get("peak_rss_kib")),
                    fmt_bytes(e.get("da_payload_bytes", 0))]
                   for e in sorted(grp, key=lambda x: (x.get("challenges", 0),
                                                       x.get("batch", 0)))]
            t = md_table(["Challenges/proof", "Batch", "Tổng cycles", "Cycles/bundle",
                          "Execute time", "Peak RSS", "Payload DA"], rq3)

            by_ch = defaultdict(list)
            for e in grp:
                by_ch[e.get("challenges")].append(e)
            lines = []
            for ch, g2 in sorted(by_ch.items(), key=lambda kv: (kv[0] is None, kv[0])):
                if len(g2) < 2:
                    continue
                cpb = [g.get("cycles_per_bundle", 0) for g in g2]
                lo, hi = min(cpb), max(cpb)
                spread = (hi - lo) / lo * 100 if lo else 0
                lines.append(f"- challenges={ch}: cycles/bundle dao động {spread:.1f}% "
                             f"({lo:,} … {hi:,}) → "
                             + ("tuyến tính tốt" if spread < 5
                                else "có overhead cố định đáng kể"))
            extra = ("\n\n### Tính tuyến tính theo batch\n" + "\n".join(lines)) if lines else ""
            parts.append(f"## tree_height = {h}\n\n" + t + extra)

        gen_note = ""
        if gens:
            gl = []
            for g in sorted(gens, key=lambda x: (x.get("tree_height", 0),
                                                 x.get("challenges", 0),
                                                 x.get("seed", 0))):
                gl.append(f"- h={g.get('tree_height')} challenges={g.get('challenges')} "
                          f"seed={g.get('seed')}: tổng {g.get('gen_s')}s "
                          f"(seal {g.get('seal_s')}s + fold {g.get('fold_s')}s), "
                          f"{fmt_bytes(g.get('bundle_bytes', 0))}, "
                          f"peak RSS {fmt_rss(g.get('peak_rss_kib'))}")
            gen_note = ("\n\n## Chi phí sinh proof phía node (Nova + Spartan)\n"
                        + "\n".join(gl))
        write(outdir, "table_rq3_overhead.md",
              "# RQ3 — Đánh đổi: tiết kiệm on-chain vs overhead off-chain\n\n"
              + "\n\n".join(parts) + gen_note + "\n")
        print(f"✅ {outdir}/table_rq3_overhead.md")

    # ── Đối chứng: bundle phân biệt vs bản sao ────────────────────────────
    # Đây là bằng chứng cho ghi chú đo đạc "N bản sao ≈ N proof phân biệt".
    dist = [e for e in execs if e.get("distinct")]
    if dist:
        ctrl = []
        for d in sorted(dist, key=lambda x: x.get("batch", 0)):
            twin = next((e for e in execs
                         if not e.get("distinct")
                         and e.get("batch") == d.get("batch")
                         and e.get("challenges") == d.get("challenges")
                         and e.get("tree_height") == d.get("tree_height")), None)
            if twin:
                dc, tc = d.get("cycles", 0), twin.get("cycles", 0)
                delta = (dc - tc) / tc * 100 if tc else 0
                ctrl.append([d.get("tree_height"), d.get("challenges"), d.get("batch"),
                             f"{tc:,}", f"{dc:,}", f"{delta:+.2f}%",
                             "✅ khớp" if abs(delta) < 2 else "⚠️ lệch đáng kể"])
            else:
                ctrl.append([d.get("tree_height"), d.get("challenges"), d.get("batch"),
                             "—", f"{d.get('cycles', 0):,}", "—",
                             "thiếu điểm bản sao cùng batch"])
        write(outdir, "table_control_distinct.md",
              "# Đối chứng — bundle PHÂN BIỆT vs BẢN SAO\n\n"
              + md_table(["tree_height", "Challenges", "Batch", "Cycles (bản sao)",
                          "Cycles (phân biệt)", "Lệch", "Kết luận"], ctrl)
              + "\n\n> Bảng này biện minh cho ghi chú đo đạc: host nhân bản một "
                "ProofBundle N lần thay vì sinh N proof phân biệt. Lệch <2% nghĩa là "
                "chi phí verify không phụ thuộc giá trị dữ liệu, đúng như lập luận.\n")
        print(f"✅ {outdir}/table_control_distinct.md")
    else:
        print("⏭️  Chưa có điểm đối chứng → chạy `./sweep.sh distinct` "
              "(reviewer sẽ hỏi về chỗ này)")

    # ── Điểm hòa vốn ──────────────────────────────────────────────────────
    if proves:
        print(f"\n📈 ĐIỂM HÒA VỐN (gas verify = {gas_verify:,}):")
        for h, grp in hgroups([p for p in proves if not p.get("distinct")]).items():
            print(f"   ── tree_height={h} ──")
            found = False
            for p in sorted(grp, key=lambda x: x.get("batch", 0)):
                gb, go = gas_pair(p.get("da_payload_bytes", 0),
                                  p.get("evm_calldata_bytes", 0), gas_verify)
                win = gb > go
                print(f"     batch={p.get('batch'):>3}: baseline {gb:>12,} gas vs "
                      f"ours {go:>10,} gas  {'✅ CÓ LỢI' if win else '❌ chưa lợi'}")
                if win and not found:
                    found = True
                    print(f"     👉 Hòa vốn từ batch = {p.get('batch')}")
            if not found:
                print("     ⚠️  Chưa batch nào có lợi — cần batch lớn hơn hoặc xem lại gas.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", help="đường dẫn results.jsonl")
    ap.add_argument("--outdir", default="analysis", help="thư mục xuất (mặc định: analysis)")
    ap.add_argument("--gas-verify", type=int, default=GAS_GROTH16_VERIFY_DEFAULT,
                    help=f"gas verify Groth16 (mặc định {GAS_GROTH16_VERIFY_DEFAULT})")
    ap.add_argument("--run-id", default=None, help="chỉ phân tích một lượt sweep")
    ap.add_argument("--tree-height", type=int, default=None,
                    help="chỉ phân tích một tree_height")
    a = ap.parse_args()
    if not os.path.exists(a.jsonl):
        print(f"❌ Không thấy {a.jsonl}", file=sys.stderr)
        sys.exit(1)
    rows = load(a.jsonl)
    if not rows:
        print("❌ File rỗng hoặc không có dòng JSON hợp lệ", file=sys.stderr)
        sys.exit(1)
    analyze(rows, a.outdir, a.gas_verify, a.run_id, a.tree_height)
    print(f"\n✅ Xong. Mở {a.outdir}/ để lấy bảng dán vào paper, và data.csv để vẽ biểu đồ.")


if __name__ == "__main__":
    main()
