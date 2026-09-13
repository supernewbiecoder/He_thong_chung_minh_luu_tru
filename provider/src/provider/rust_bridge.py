"""
═══════════════════════════════════════════════════════════════════════════════
 CẦU SANG MẠCH RUST  ·  niêm phong và chứng minh THẬT
═══════════════════════════════════════════════════════════════════════════════

 Tầng Python lo điều phối, DA, worker, aggregator. Tầng Rust lo mạch. Mô-đun
 này là chỗ hai bên gặp nhau.

 ── CÁI GÌ THẬT, CÁI GÌ KHÔNG ───────────────────────────────────────────────

 THẬT, chạy trên máy đang chạy:
     niêm phong sector, đọc theo luồng từ file
     Nova IVC gấp qua từng thách thức
     nén Spartan ra bằng chứng 13.776 byte
     xác minh bằng chứng đó

 KHÔNG THẬT, và có nhãn ở chỗ khác:
     gói SP1 và bằng chứng Groth16 — SP1 chỉ execute được, prove thì hết bộ nhớ
     ở 35 GB, nên tầng aggregator dùng mock. Xem `HE_THONG_THAT.md`.

 ── THUẬT TOÁN NIÊM PHONG: HAI BẢN, ĐỌC KỸ ──────────────────────────────────

 Mạch Rust hiện thực **Thuật toán 1c**: R_i = H4(D_i, S_{i-1}, i, replica_id).
 KHÔNG có fan-in.

 `provider/sealing.py` hiện thực **SeqWide** có fan-in φ=6. Bản đó là THIẾT KẾ
 và MÔ PHỎNG, chưa vào mạch: đưa fan-in vào mạch đòi witness thêm 5 trạng thái
 và 5 đường Merkle để buộc chúng vào `sealed_root`, tức khoảng 6 lần số phép
 băm Merkle trong mạch. Đó là một lần sửa mạch thật, không phải vá nhỏ.

 Hai bản cùng nằm trong repo là CỐ Ý, và chỗ nào dùng bản nào thì ghi rõ. Số
 liệu đo được từ mô-đun này là số của Thuật toán 1c.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CIRCUIT_DIR = REPO_ROOT / "circuit"
BIN_DIR = CIRCUIT_DIR / "target" / "release"


class CircuitUnavailable(RuntimeError):
    """Chưa build mạch Rust.

    Ném lỗi rõ ràng thay vì âm thầm rơi về mô hình chi phí: một lần chạy tưởng
    là thật mà hoá ra là mô hình thì tệ hơn một lần chạy hỏng.
    """


def binary(name: str) -> Path:
    p = BIN_DIR / name
    if not p.exists():
        raise CircuitUnavailable(
            f"không thấy {p}. Chạy:\n"
            f"    cd circuit && cargo build --release -p prover --bin {name}\n"
            f"Cần Rust ≥ 1.85 (edition2024 trong cây phụ thuộc)."
        )
    return p


def available() -> bool:
    return (BIN_DIR / "engram_prove").exists() and (BIN_DIR / "engram_verify").exists()


@dataclass
class ProofArtifacts:
    """Kết quả một lần chứng minh THẬT."""

    proof: bytes           # đúng byte sẽ lên Celestia
    out_dir: Path          # chứa proof.bin, vk.bin, z0.bin
    sealed_root: str
    challenges: list[int]
    n_steps: int
    seal_ms: float
    setup_ms: float
    prove_ms: float
    verify_ms: float
    verify_ok: bool

    @property
    def proof_bytes(self) -> int:
        return len(self.proof)


def prove(
    *,
    sector_path: Path,
    out_dir: Path,
    n_chunks: int = 16,
    chunk_size: int = 4096,
    tree_height: int | None = None,
    challenges: int = 3,
    sector_id: int = 7,
    epoch: int = 0,
    replica: str = "engram-replica-id",
    beacon: str = "engram-beacon-000",
    timeout_s: int = 1800,
) -> ProofArtifacts:
    """Niêm phong sector rồi sinh bằng chứng. Mọi số trả về là ĐO, không mô hình.

    `tree_height` bỏ trống thì DẪN XUẤT từ `n_chunks`: cây Merkle trên n lá cần
    chiều cao ceil(log2 n).

    ── VÌ SAO KHÔNG ĐỂ MẶC ĐỊNH CỨNG ──────────────────────────────────────

    Bản trước ghim `tree_height = 4`, tức 16 lá. Chạy với 64 chunk thì cây có
    độ sâu 6, đường Merkle dài 6, nhưng mạch vẫn lặp 4 tầng — ra gốc khác
    `sealed_root`, và verify TỪ CHỐI.

    Điều tệ nhất không phải việc sai, mà là nó sai IM LẶNG: `engram_prove` vẫn
    sinh ra một `proof.bin` đúng 13.776 byte trông hoàn toàn bình thường, chỉ
    tới bước verify mới lộ. Phát hiện được nhờ quét quy mô sector, 16 chunk thì
    ĐẠT còn 64 và 256 thì FAIL.
    """
    if tree_height is None:
        tree_height = max(1, (n_chunks - 1).bit_length())
    cmd = [
        str(binary("engram_prove")),
        "--sector", str(sector_path),
        "--out", str(out_dir),
        "--chunks", str(n_chunks),
        "--chunk-size", str(chunk_size),
        "--tree-height", str(tree_height),
        "--challenges", str(challenges),
        "--sector-id", str(sector_id),
        "--epoch", str(epoch),
        "--replica", replica,
        "--beacon", beacon,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    line = _last_json_line(res.stdout)
    if line is None:
        raise CircuitUnavailable(
            f"engram_prove không trả JSON (mã thoát {res.returncode}).\n"
            f"stdout cuối: {res.stdout[-400:]}\nstderr: {res.stderr[-400:]}"
        )
    d = json.loads(line)
    proof = (Path(d["out_dir"]) / "proof.bin").read_bytes()
    return ProofArtifacts(
        proof=proof,
        out_dir=Path(d["out_dir"]),
        sealed_root=d["sealed_root"],
        challenges=d["challenges"],
        n_steps=len(d["challenges"]),
        seal_ms=d["seal_ms"],
        setup_ms=d["setup_ms"],
        prove_ms=d["prove_ms"],
        verify_ms=d["verify_ms"],
        verify_ok=d["verify_ok"],
    )


def verify(proof_dir: Path, steps: int, proof_override: bytes | None = None,
           timeout_s: int = 600) -> dict:
    """Xác minh bằng chứng trong `proof_dir`.

    `proof_override` cho phép verify đúng BYTE ĐỌC TỪ DA thay vì byte trên đĩa
    của prover. Đó mới là đường đi thật: worker không đọc đĩa của nút, nó đọc
    Celestia. Nếu ai đó thay blob giữa chừng thì verify phải trả false — và có
    test chốt điều đó.
    """
    proof_dir = Path(proof_dir)
    if proof_override is not None:
        tmp = proof_dir.parent / (proof_dir.name + "-from-da")
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(proof_dir, tmp)
        (tmp / "proof.bin").write_bytes(proof_override)
        proof_dir = tmp

    res = subprocess.run(
        [str(binary("engram_verify")), "--dir", str(proof_dir), "--steps", str(steps)],
        capture_output=True, text=True, timeout=timeout_s,
    )
    line = _last_json_line(res.stdout)
    if line is None:
        return {"verify_ok": False, "reason": f"không trả JSON: {res.stderr[-300:]}"}
    return json.loads(line)


def _last_json_line(out: str) -> str | None:
    """Binary in cả log tiếng Việt lẫn JSON; lấy dòng JSON cuối."""
    for ln in reversed(out.strip().splitlines()):
        ln = ln.strip()
        if ln.startswith("{") and ln.endswith("}"):
            return ln
    return None
