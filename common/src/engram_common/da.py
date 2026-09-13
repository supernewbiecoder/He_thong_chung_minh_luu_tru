"""
═══════════════════════════════════════════════════════════════════════════════
 TẦNG DA  ·  một giao diện, hai backend
═══════════════════════════════════════════════════════════════════════════════

 Cùng một đoạn mã worker chạy được trên cả hai:

     MemoryDA      trong tiến trình, không cần mạng, dùng cho test và CI
     CelestiaDA    devnet Celestia cục bộ hoặc testnet Mocha, JSON-RPC thật

 ── VÌ SAO PHẢI CÓ CẢ HAI ───────────────────────────────────────────────────

 `MemoryDA` một mình thì mọi kết luận chỉ nói về một danh sách trong RAM. Nó
 không kiểm được ba thứ mà thiết kế dựa vào, và cả ba đều thuộc về Celestia
 chứ không thuộc về Engram:

     ① trường signer của share phiên bản 1 có thật sự được đồng thuận áp đặt
     ② namespace có thật sự mở cho mọi người ghi
     ③ một blob có thật sự lên được block trong cửa sổ W

 `CelestiaDA` một mình thì không chạy được trong CI, và mỗi lần chạy test phải
 dựng devnet.

 ── SHARE PHIÊN BẢN 1, KHÔNG PHẢI 0 ─────────────────────────────────────────

 `submit` dùng `share_version = 1` và điền `signer`. Đây KHÔNG phải lựa chọn
 thẩm mỹ: toàn bộ phòng thủ chống mạo danh blob (§J.2.1) dựa vào trường đó.
 Với share version 0 thì blob không mang signer, worker không phân biệt được ai
 đăng, và bộ lọc F3b vô nghĩa.

 Trường signer vào Celestia từ CIP-21 "Introduce blob type with verified
 signer", nằm trong bản nâng cấp Ginger tức celestia-app v3 — kích hoạt Arabica
 5/11/2024, Mocha tháng 11/2024, Mainnet Beta tháng 12/2024. Nên đây không phải
 tính năng thử nghiệm.

 ── MỘT ĐIỀU DỄ HIỂU NHẦM, GHI RÕ ───────────────────────────────────────────

 Trường signer cho ATTRIBUTION, không cho ADMISSION CONTROL. Kẻ ngoài VẪN đăng
 được blob vào namespace của mình — namespace không có chủ và Celestia không có
 cơ chế khoá ghi. Thứ nó không làm được là điền signer thành địa chỉ của người
 khác. Nên rác vẫn vào block và worker vẫn phải tải; cái rẻ đi là việc LOẠI nó,
 chỉ tốn một phép so sánh 20 byte.

 `MemoryDA.read` vì thế trả về MỌI thứ ai đó đã ghi, kể cả rác. Đó là hành vi
 đúng, không phải thiếu sót.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .blob import HEADER_SIZE, BlobHeader, ObservedBlob
from .crypto import keccak

SHARE_SIZE = 512
NAMESPACE_SIZE = 29


_B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def bech32_to_bytes(addr: str) -> bytes:
    """Giải mã địa chỉ bech32 của Cosmos thành 20 byte.

    Không dùng thư viện ngoài: cả repo chạy bằng thư viện chuẩn, và một phép
    giải mã 20 dòng không đáng để thêm phụ thuộc.
    """
    addr = addr.strip().lower()
    pos = addr.rfind("1")
    if pos < 1:
        raise DAError(f"địa chỉ bech32 không hợp lệ: {addr!r}")
    data = addr[pos + 1 :]
    try:
        vals = [_B32.index(c) for c in data[:-6]]      # bỏ 6 ký tự checksum
    except ValueError as e:
        raise DAError(f"ký tự không thuộc bảng bech32 trong {addr!r}: {e}")

    acc, bits, out = 0, 0, bytearray()
    for v in vals:
        acc = (acc << 5) | v
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    if len(out) != 20:
        raise DAError(f"địa chỉ giải ra {len(out)} byte, cần 20: {addr!r}")
    return bytes(out)


class DAError(RuntimeError):
    pass


class DALayer(Protocol):
    """Giao diện mà worker và aggregator nhìn thấy."""

    def submit(self, namespace: bytes, header: BlobHeader, payload: bytes,
               signer: bytes) -> int: ...

    def read(self, namespace: bytes, start: int, end: int) -> list[ObservedBlob]: ...

    def head_height(self) -> int: ...

    def data_roots(self, heights: list[int]) -> list[bytes]: ...


# ═══════════════════════════════════════════════════════════════════════════
# 1. BACKEND BỘ NHỚ
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class MemoryDA:
    """Celestia trong bộ nhớ. Namespace MỞ — ai cũng ghi vào được, kể cả rác."""

    height: int = 1_000_000
    entries: list[tuple[bytes, ObservedBlob]] = field(default_factory=list)

    def advance(self, n: int = 1) -> int:
        self.height += n
        return self.height

    def head_height(self) -> int:
        return self.height

    def submit(self, namespace: bytes, header: BlobHeader, payload: bytes,
               signer: bytes) -> int:
        if len(namespace) != NAMESPACE_SIZE:
            raise DAError(f"namespace phải {NAMESPACE_SIZE} byte, nhận {len(namespace)}")
        if len(signer) != 20:
            raise DAError(f"signer phải 20 byte, nhận {len(signer)}")
        idx = sum(1 for _, b in self.entries if b.height == self.height)
        self.entries.append(
            (namespace, ObservedBlob(self.height, idx, signer, header, payload))
        )
        return self.height

    def read(self, namespace: bytes, start: int, end: int) -> list[ObservedBlob]:
        return [b for ns, b in self.entries
                if ns == namespace and start <= b.height < end]

    def data_roots(self, heights: list[int]) -> list[bytes]:
        return [keccak(b"DATA_ROOT", h.to_bytes(8, "little")) for h in heights]

    def square_roots(self, heights: list[int]) -> list[int]:
        """Số gốc hàng+cột mỗi block — dùng để đo độ lấp đầy cửa sổ.

        Bộ nhớ không có square thật, nên suy từ số share đã ghi ở mỗi block.
        """
        out = []
        for h in heights:
            shares = sum(
                (len(b.payload) + SHARE_SIZE - 1) // SHARE_SIZE
                for _, b in self.entries if b.height == h
            )
            side = 1
            while side * side < max(1, shares):
                side *= 2
            out.append(2 * 2 * side)  # square mở rộng gấp đôi mỗi chiều
        return out


# ═══════════════════════════════════════════════════════════════════════════
# 2. BACKEND CELESTIA THẬT
# ═══════════════════════════════════════════════════════════════════════════


class CelestiaDA:
    """JSON-RPC tới celestia-node.

    Tên method đối chiếu Node API của celestia-node v0.28.x:

        blob.Submit(blobs, options)       -> height
        blob.GetAll(height, [namespace])
        blob.GetProof(height, ns, commitment)
        header.GetByHeight(height)        -> có dah.row_roots, data_hash
        header.NetworkHead()

    Node version khác mà đổi tên method thì sửa Ở ĐÂY, vì mọi chỗ khác gọi qua
    lớp này.
    """

    TESTNETS = {"mocha", "mocha-4", "arabica", "arabica-11"}

    def __init__(self, url: str | None = None, token: str | None = None,
                 timeout: int = 120):
        self.url = url or os.environ.get("CELESTIA_RPC", "http://127.0.0.1:46658")
        self.token = token if token is not None else os.environ.get(
            "CELESTIA_AUTH_TOKEN", ""
        )
        self.timeout = timeout
        self._id = 0
        self._addr: str | None = None

    # ── ống RPC ────────────────────────────────────────────────────────────

    def call(self, method: str, params: list):
        self._id += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        ).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise DAError(f"HTTP {e.code} khi gọi {method}: {e.read()[:300]}")
        except urllib.error.URLError as e:
            raise DAError(
                f"Không nối được {self.url} ({e.reason}). Kiểm: node chạy chưa, "
                f"cổng đúng chưa, CELESTIA_RPC đúng chưa."
            )
        if body.get("error") is not None:
            raise DAError(f"{method} lỗi: {body['error']}")
        return body.get("result")

    # ── cổng an toàn ───────────────────────────────────────────────────────

    def _guard_submit(self) -> None:
        """Chặn công bố blob lên mạng chính, không có ngoại lệ nào.

        Một lần chạy thử không được phép tiêu TIA thật. Hai cách mở, chọn ĐÚNG
        MỘT:

            CELESTIA_LOCAL_DEVNET=1   node loopback trên chính máy này
            CELESTIA_NETWORK=mocha    testnet công khai, TIA lấy từ faucet
        """
        devnet = os.environ.get("CELESTIA_LOCAL_DEVNET", "0") == "1"
        network = os.environ.get("CELESTIA_NETWORK", "").strip().lower()
        if network in {"celestia", "mainnet"}:
            raise DAError(
                "CELESTIA_NETWORK trỏ tới mạng chính. Mã này không công bố blob "
                "lên mạng chính trong bất kỳ trường hợp nào."
            )
        if not devnet and network not in self.TESTNETS:
            raise DAError(
                "Công bố blob đang tắt. Đặt CELESTIA_LOCAL_DEVNET=1 (node "
                "loopback) hoặc CELESTIA_NETWORK=mocha (testnet công khai). "
                f"Hiện: LOCAL_DEVNET={os.environ.get('CELESTIA_LOCAL_DEVNET','0')} "
                f"NETWORK={network or '(trống)'}"
            )

    # ── các lệnh ───────────────────────────────────────────────────────────

    def head_height(self) -> int:
        h = self.call("header.NetworkHead", [])
        return int(h["header"]["height"])

    def submit(self, namespace: bytes, header: BlobHeader, payload: bytes,
               signer: bytes, gas_price: float = -1.0) -> int:
        """Công bố blob với share_version = 1.

        `signer` KHÔNG được node lấy từ tham số này: đồng thuận điền nó bằng
        địa chỉ đã ký giao dịch. Truyền vào để lớp gọi khai báo ý định, và để
        `MemoryDA` có cùng chữ ký. Nếu khoá của node khác `signer`, blob lên
        chain sẽ mang địa chỉ của node — và worker sẽ loại nó. Đó là hành vi
        đúng, không phải lỗi.
        """
        self._guard_submit()
        if len(namespace) != NAMESPACE_SIZE:
            raise DAError(f"namespace phải {NAMESPACE_SIZE} byte, nhận {len(namespace)}")
        # ── `signer` BẮT BUỘC, và phải khớp khoá của chính node ────────────
        #
        # Hai lần thử, hai lỗi, và cả hai đều là bằng chứng cho §J.2.1:
        #
        #   ① điền địa chỉ tuỳ ý →
        #      "blob signer E41F3584… does not match MsgPayForBlobs signer
        #       5FD07CB6… : invalid blob signer"
        #      Đồng thuận ĐỐI CHIẾU trường signer với người ký giao dịch.
        #
        #   ② bỏ trường đi →
        #      "share version 1 requires signer of size 20bytes"
        #      Node KHÔNG tự điền; share v1 bắt buộc có.
        #
        # Nên chỉ còn một đường đúng: hỏi node địa chỉ của chính nó. Đó cũng là
        # địa chỉ mà nút PHẢI đăng ký ở `registerProvider` — đăng ký sai thì blob
        # của chính nó bị bộ lọc F3b loại, và nó tự biến mình thành ABSENT.
        if signer != self.signer_bytes():
            signer = self.signer_bytes()

        blob = {
            "namespace": base64.b64encode(namespace).decode(),
            "data": base64.b64encode(header.pack() + payload).decode(),
            "share_version": 1,
            "signer": base64.b64encode(signer).decode(),
        }
        return int(self.call("blob.Submit", [[blob], {"gas_price": gas_price}]))

    def account_address(self) -> str:
        """Địa chỉ bech32 mà node này ký giao dịch bằng, ví dụ `celestia1…`."""
        if self._addr is None:
            self._addr = self.call("state.AccountAddress", [])
        return self._addr

    def signer_bytes(self) -> bytes:
        """20 byte tương ứng — đúng giá trị sẽ nằm trong trường signer của share."""
        return bech32_to_bytes(self.account_address())

    def read(self, namespace: bytes, start: int, end: int) -> list[ObservedBlob]:
        """Đọc mọi blob trong namespace, trên khoảng chiều cao nửa mở [start, end).

        Trả về CẢ rác của người khác — namespace không có chủ. Việc lọc là của
        worker, không phải của tầng này.
        """
        ns_b64 = base64.b64encode(namespace).decode()
        out: list[ObservedBlob] = []
        for h in range(start, end):
            try:
                blobs = self.call("blob.GetAll", [h, [ns_b64]]) or []
            except DAError as e:
                # Block không có blob nào trong namespace → node trả lỗi thay vì
                # danh sách rỗng. Đó là vắng mặt, không phải hỏng.
                if "not found" in str(e).lower():
                    continue
                raise
            for idx, b in enumerate(blobs):
                raw = base64.b64decode(b["data"])
                signer = base64.b64decode(b.get("signer") or "") or b"\x00" * 20
                out.append(ObservedBlob(
                    height=h, index=idx, signer=signer,
                    header=BlobHeader.unpack(raw), payload=raw[HEADER_SIZE:],
                ))
        return out

    def data_roots(self, heights: list[int]) -> list[bytes]:
        out = []
        for h in heights:
            hdr = self.call("header.GetByHeight", [h])
            out.append(bytes.fromhex(hdr["dah"]["data_root"])
                       if "data_root" in hdr.get("dah", {})
                       else base64.b64decode(hdr["header"]["data_hash"]))
        return out

    def square_roots(self, heights: list[int]) -> list[int]:
        """Số gốc hàng+cột mỗi block, đọc từ `dah` của header.

        Đây là đại lượng mà `prove_coverage` dùng để đo độ lấp đầy cửa sổ, và
        là bằng cớ KHÁCH QUAN về nghẽn DA: nút không tự dựng lên được, muốn
        dựng phải thật sự trả tiền lấp đầy block.
        """
        out = []
        for h in heights:
            hdr = self.call("header.GetByHeight", [h])
            dah = hdr.get("dah", {})
            out.append(len(dah.get("row_roots", [])) + len(dah.get("column_roots", [])))
        return out


# ═══════════════════════════════════════════════════════════════════════════
# 3. CHỌN BACKEND
# ═══════════════════════════════════════════════════════════════════════════


def make_da(kind: str | None = None):
    """Chọn backend theo `ENGRAM_DA`, mặc định `memory`.

        ENGRAM_DA=memory     trong tiến trình, không cần mạng
        ENGRAM_DA=celestia   JSON-RPC, đòi CELESTIA_LOCAL_DEVNET hoặc _NETWORK
    """
    kind = (kind or os.environ.get("ENGRAM_DA", "memory")).strip().lower()
    if kind == "memory":
        return MemoryDA()
    if kind == "celestia":
        return CelestiaDA()
    raise DAError(f"ENGRAM_DA không hợp lệ: {kind!r}. Dùng 'memory' hoặc 'celestia'.")
