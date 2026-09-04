# Lộ trình kiểm thử

Ba giai đoạn, theo thứ tự. Không nhảy cóc: mỗi giai đoạn giả định giai đoạn
trước đã xanh, và lỗi phát hiện ở giai đoạn sau thì tốn gấp bội để truy nguyên.

---

## Giai đoạn 1 — Offline, không cần mạng

**Mục tiêu:** mọi đường mã chạy qua ít nhất một lần, kết quả tất định, lặp lại
được. Không có biến động mạng nào che mất lỗi logic.

```
CHAIN_MODE=local make sim
```

| Thành phần | Thay bằng | Ghi chú |
|---|---|---|
| Celestia | `da-mock` trong container | tập con API blob, giữ trong bộ nhớ |
| Blobstream | `MockBlobstream` | có `setOutage` để bật/tắt sự cố |
| EVM | Anvil | chạy **đúng** EVM nên gas là THẬT |
| Groth16 | `MockVerifier` | vẫn kiểm độ dài 356 B vì độ dài ảnh hưởng gas |

**Xong giai đoạn 1 khi:**

- [ ] Bảy kịch bản KB-01…KB-07 chạy hết, không lỗi
- [ ] `forge test --gas-report` cho `commitEpoch` ≈ 487.109 gas
- [ ] Chạy hai lần cùng hạt giống ra cùng `new_state_root`
- [ ] Có ít nhất một `PASS`, một `FAIL`, một `ABSENT`, một `NONE` trong CSV
- [ ] Chuỗi trạng thái không đứt qua 3 epoch

---

## Giai đoạn 2 — Celestia Mocha thật, EVM vẫn Anvil

> **ĐÂY LÀ MỤC NHẮC BẠN YÊU CẦU.**
>
> Sau khi giai đoạn 1 xanh, **chuyển sang Mocha** để thử những thứ mà bản mock
> không tái hiện được. Đây không phải bước "chạy lại cho chắc" — nó kiểm một
> lớp vấn đề hoàn toàn khác.

```
CHAIN_MODE=mocha-anvil make sim-mocha
```

**Những thứ chỉ Mocha mới lộ ra:**

| Hiện tượng | Vì sao mock không tái hiện | Ảnh hưởng phần nào của đặc tả |
|---|---|---|
| **Rớt mạng giữa cửa sổ nộp** | mock không bao giờ rớt | nút lỡ `timeout_height` → `ABSENT`. Kiểm §F.2.5: có đúng là **không** chấp nhận bằng chứng muộn không |
| **Block Celestia trễ nhịp** | mock ra block đều tăm tắp | cửa sổ *W* = 6 block ở hồ sơ sim có đủ không, hay sinh `ABSENT` giả |
| **Blob không vào được block** | mock nhận mọi thứ | mempool đầy, phí thấp bị bỏ. Kiểm nút có phát hiện và báo không |
| **Độ trễ chung kết thật** | mock chung kết tức thì | δ = 2 block có đủ để mọi nút thấy header chưa (§F.2.2) |
| **Phí DA biến động** | mock miễn phí | con số 0,00024 $ mỗi blob có đúng ở giá thật không |
| **Trường `signer` thật trong share v1** | mock tự điền | **quan trọng nhất** — kiểm Celestia thật sự áp đặt trường này, tức nền của §J.2.1 |
| **Namespace bị người khác ghi vào** | mock chỉ có ta | đúng tình huống §J.2.1, quan sát trên mạng thật |

**Cách chủ động gây rớt mạng để thử:**

```bash
# Ngắt nút khỏi mạng giữa cửa sổ nộp
docker network disconnect engram_engram engram-provider-a-1
sleep 40
docker network connect engram_engram engram-provider-a-1

# Làm chậm và mất gói, giống mạng kém
docker exec engram-provider-a-1 tc qdisc add dev eth0 root netem delay 800ms loss 20%

# Cho Blobstream treo, kiểm epoch kẹt ở COMMITTED mà KHÔNG AI MẤT TIỀN
cast send $BLOBSTREAM "setOutage(bool)" true --rpc-url http://localhost:8545
```

**Xong giai đoạn 2 khi:**

- [ ] Nút rớt mạng giữa cửa sổ → nhận `ABSENT`, **không bị phạt nặng**, và
      epoch sau vẫn chạy tiếp bình thường
- [ ] Blobstream treo → epoch kẹt `COMMITTED`, `claimSettlement` đóng, **không
      ai mất tiền**, và mở lại thì `finalizeEpoch` chạy được (§F.2.4)
- [ ] Trường `signer` đọc từ share v1 thật khớp địa chỉ đã đăng ký
- [ ] Phí DA thật nằm trong ±20 % con số 0,00024 $
- [ ] *W* = 6 block **không** sinh `ABSENT` giả trong 20 lần chạy liên tiếp —
      nếu có thì nới *W* trong hồ sơ sim, đừng ép nút

---

## Giai đoạn 3 — Mocha + Sepolia, có Blobstream thật

```
CHAIN_MODE=mocha-sepolia make sim-mocha
```

Đây là lần đầu **toàn bộ chuỗi bốn tầng** chạy thật, gồm cả bước
`finalizeEpoch` gọi Blobstream thật.

**Xong giai đoạn 3 khi:**

- [ ] Một epoch đi trọn `Open → Committed → Final`
- [ ] Gas `commitEpoch` trên Sepolia khớp con số Anvil
- [ ] Cửa sổ epoch **thẳng hàng với ranh giới dải nonce** của Blobstream —
      nếu vắt qua hai dải thì phải chỉnh `H₀` hoặc `L_d` (§D.2.5 ④)
- [ ] Độ trễ `Committed → Final` đo được, đối chiếu với chu kỳ cập nhật mặc
      định một giờ của Blobstream

---

## Ba thứ **không** kiểm được ở giai đoạn nào

Ghi ra để không ai tưởng đã kiểm rồi:

**Bằng chứng mật mã thật.** Bản mô phỏng dùng mô hình chi phí, nên nó **không**
chứng minh Nova/Spartan/SP1 đúng. Nó chứng minh *giao thức xung quanh* đúng.

**Thời gian niêm phong thật.** 1,26 giờ là con số mô hình quy chiếu từ số đo
`sealbench`. Muốn số thật phải chạy `bundle_gen` trên máy đích (§M.2.3 mục 1).

**Hành vi ở quy mô lớn.** 20 hợp đồng không lộ ra vấn đề của 10.000. Riêng
NFR-05 (`D·S_ns ≤ N/20`) chỉ kiểm được bằng tính toán, không bằng chạy thử.

---

## Phụ lục — cài trên `node-blockchain`

Máy chủ này **đang chạy việc của người khác**. Ba nguy cơ giẫm chân, và cách đã xử lý:

| Nguy cơ | Đã xử lý thế nào |
|---|---|
| `~/engram` đã tồn tại (clone repo cũ) | Cài vào thư mục khác: `~/engram-sim` |
| Cổng 26658 là celestia-node, 8545/8547 là EVM/nitro | Mọi cổng dời sang dải **18xxx**, đổi được qua `.env` |
| Tên container Docker trùng | Project name `engram-sim`, mạng riêng, không dùng host network |

### Cài

```bash
cd ~
tar xzf engram_code.tar.gz
mv engram engram-sim          # ← BẮT BUỘC, tránh đè repo cũ ~/engram
cd engram-sim
cp .env.example .env
make preflight                # kiểm cổng, container, đĩa, RAM
make check                    # đối chiếu mã ↔ đặc tả rồi chạy thử
```

`make check` **không cần Docker, không cần mạng** — chạy trong tiến trình, ~2 giây.
Nếu preflight báo xung đột thì đổi dải cổng:

```bash
ENGRAM_PORT_ANVIL=19545 ENGRAM_PORT_DAMOCK=19658 make preflight
```

### Tin tốt — ba thứ đã có sẵn trên máy

Giai đoạn 2 và 3 dễ hơn dự tính, vì hạ tầng Blobstream đã nằm sẵn ở đó:

| Thư mục | Dùng cho |
|---|---|
| `~/celestia-node`, `~/celestia_client` | giai đoạn 2 — Celestia thật, **không cần dựng lại** |
| `~/sp1-blobstream` | giai đoạn 3 — hợp đồng Blobstream. Lấy địa chỉ đã deploy đặt vào `BLOBSTREAM_ADDR` |
| `~/orchestrator-relayer` | giai đoạn 3 — relayer đẩy `DataRootTupleRoot` lên EVM |

Nghĩa là **có thể bỏ qua phần khó nhất của giai đoạn 3**: không phải tự deploy Blobstream
và tự chạy relayer. Chỉ cần trỏ `CHAIN_MODE=mocha-sepolia` vào những gì đang chạy.

**Kiểm trước khi dùng:** relayer có đang chạy và cập nhật nonce đều không? Nếu nó dừng thì
`finalizeEpoch` sẽ treo — và đó chính là kịch bản sự cố ở giai đoạn 2, nên dù sao cũng phải thử.

### Đừng làm

- **Đừng** `docker compose down -v` ở `~` — có `docker-compose.yml.save` của việc khác
- **Đừng** chạy `make sim` khi chưa qua `make preflight`
- **Đừng** đặt thư mục tên `engram` — sẽ đè repo đã clone
