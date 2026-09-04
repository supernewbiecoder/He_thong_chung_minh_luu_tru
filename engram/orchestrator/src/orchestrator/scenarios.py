"""
[SPEC §L] Bảy kịch bản chạy tay KB-01…KB-07, thành mã chạy được.

Mỗi kịch bản trả về một dict số liệu, orchestrator gom lại xuất CSV.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_root = Path(__file__).resolve().parents[3]
for sub in ("common", "worker", "aggregator", "provider", "client"):
    sys.path.insert(0, str(_root / sub / "src"))

from engram_common.constants import PROFILE_SIM  # noqa: E402
from engram_common.verdict import Verdict  # noqa: E402
from aggregator.aggregate import CoverageGapError, aggregate_epoch  # noqa: E402
from worker.lottery import (  # noqa: E402
    LotteryStats, WorkerEntry, cooldown_deadlines, record_outcome,
    required_workers, worker_lottery,
)
from worker.verify import ExpectedDeal, verify_shard  # noqa: E402

from .harness import SimNetwork


def run_deadline(net: SimNetwork, epoch: int, d_idx: int, attack_target=None, n_decoys: int = 0):
    """KB-03 — một deadline trọn vẹn."""
    slot = net.clock.slot_at(epoch, d_idx)
    net.da.height = slot.window_start
    deadline_abs = slot.absolute_deadline

    due = [d for d in net.deals if d.deadline_idx == d_idx]
    net.publish_bundles(deadline_abs, due)
    if attack_target is not None and n_decoys:
        net.publish_decoys(deadline_abs, attack_target, n_decoys)
    net.da.advance(PROFILE_SIM.submit_window_blocks)

    total_cells = PROFILE_SIM.deadlines_per_epoch * net.n_shards
    results = []
    for shard in range(net.n_shards):
        chosen = worker_lottery(
            net.beacon(slot), shard, net.worker_pool,
            deadline=deadline_abs, r=2, assigned_count=net.assigned,
            total_cells=total_cells, cooldown=net.cooldown, stats=net.lottery_stats,
        )
        expected = [
            ExpectedDeal(d.provider_id, d.deal_id, d.sealed_root, d.declared)
            for d in due if d.shard == shard
        ]
        observed = net.da.read(net.namespace(shard), slot.window_start, net.da.height)
        for w in chosen:  # r worker cùng chạy, hoà giải ở aggregator
            # [CHỐT F3] Worker "chết" mô phỏng: không nộp ChildProof.
            if w.worker_id in net.dead_workers:
                record_outcome(w, False, deadline_abs)
                continue
            record_outcome(w, True, deadline_abs)
            results.append(
                verify_shard(
                    deadline=deadline_abs, shard=shard, namespace=net.namespace(shard),
                    expected=expected, observed=observed, signer_of=net.signer_of,
                    height_start=slot.window_start, height_end=net.da.height,
                    sha_cycles=net.sha_cycles,
                )
            )
    return results


def run_epoch(net: SimNetwork, epoch: int, **kw) -> dict[str, Any]:
    """KB-04 — cam kết cả epoch."""
    all_results = []
    for d in range(PROFILE_SIM.deadlines_per_epoch):
        all_results += run_deadline(net, epoch, d, **kw)

    try:
        pv, proof, leaves = aggregate_epoch(
            epoch=epoch, chain_id=net.chain_id, shard_results=all_results,
            expected_shards=set(range(net.n_shards)),
            expected_deadlines=PROFILE_SIM.deadlines_per_epoch * 2,  # r=2 bản mỗi ô
            prev_state_root=bytes(32), da_commitment=b"\xda" * 32, da_nonce=812,
            submitter=b"\x7e" * 20, storage_vk_digest=b"\x05" * 32, snapshot_id=b"\x06" * 32,
        )
        gap = None
    except CoverageGapError as e:
        pv, proof, leaves, gap = None, None, [], str(e)

    counts = {v.name: 0 for v in Verdict}
    for lf in leaves:
        counts[lf.verdict.name] += 1

    return {
        "epoch": epoch,
        "cells": len(all_results),
        "cycles_e9": round(sum(r.cycles for r in all_results) / 1e9, 1),
        "sha256_ops": sum(r.coverage.sha256_ops for r in all_results),
        "decoys_dropped": sum(r.filter_stats.drop_signer for r in all_results),
        "calldata_bytes": (len(pv.pack()) + len(proof)) if pv else 0,
        "coverage_gap": gap,
        **{f"n_{k.lower()}": v for k, v in counts.items()},
    }
