# Hướng dẫn chạy — từ con số 0

Viết cho máy chủ `node-blockchain`, nơi **đang chạy việc của người khác**.

## Nguyên tắc: cô lập hoàn toàn

Không dùng lại bất cứ thứ gì đã có trên máy. Hai lý do, và cả hai đều quan trọng:

**Vì bài báo.** Nếu số đo của bạn phụ thuộc một Blobstream do người khác cấu
hình, một relayer bạn không kiểm soát, một light node có lịch sử không rõ — thì
bạn **không mô tả lại được thiết lập trong bài**, và người phản biện hỏi "chạy
trên cấu hình nào" là không trả lời nổi. Số đo không tái lập được là số đo không
dùng được.

**Vì người khác.** `~/celestia-node`, `~/sp1-blobstream`, `~/orchestrator-relayer`
đang phục vụ việc của ai đó. Chạy đè lên là phá.

| Thứ trên máy | Cách xử lý |
|---|---|
| `~/engram` (repo cũ) | **không đụng** — cài vào `~/engram-sim` |
| `~/celestia-node`, `~/celestia_client` | **không đụng** — dựng light node riêng nếu cần |
| `~/sp1-blobstream` | **không đụng** — dùng địa chỉ canonical công khai |
| `~/orchestrator-relayer` | **không đụng** — không chạy relayer riêng |
| `~/docker-compose.yml.save` | **không đụng** — đừng chạy `docker compose` ở `~` |
| cổng 26658, 8545, 8547, 9944 | **không đụng** — mọi cổng của ta ở dải 18xxx |

Ranh giới: **hạ tầng công cộng thì dùng được** — mạng Celestia Mocha, Sepolia,
địa chỉ Blobstream canonical. Chúng không nằm "trên máy", và bài báo trích dẫn
được. Chỉ tránh **thực thể riêng của người khác**.

---

# Bước 1 — Lấy mã và chạy offline

Bước này **không cần Docker, không cần mạng, không cần Foundry**. Mục tiêu: xác
nhận mã chạy và khớp đặc tả trước khi dựng bất cứ thứ gì.

```bash
cd ~
git clone https://github.com/supernewbiecoder/He_thong_chung_minh_luu_tru.git engram-sim
cd engram-sim
```

> **Tên thư mục phải là `engram-sim`.** Mặc định `git clone` sẽ đặt tên
> `He_thong_chung_minh_luu_tru`, cũng được — miễn **không phải `engram`**, vì
> `~/engram` đã có repo cũ.

Kiểm phiên bản Python:

```bash
python3 --version        # cần ≥ 3.11
```

Chạy:

```bash
make preflight    # kiểm cổng, container, đĩa, RAM
make check        # đối chiếu mã ↔ đặc tả, rồi chạy mô phỏng
```

### Cần thấy gì

`make preflight` in ra danh sách cổng, và dòng cuối:

```
  ✓ Không xung đột. Chạy được:  make check
```

`make check` in ra bốn dòng `OK`, rồi kết quả mô phỏng:

```
  common/tests/test_spec_consistency.py         OK
  common/tests/test_blob_impersonation.py       OK
  provider/tests/test_fanin_closure.py          OK
  worker/tests/test_lottery.py                  OK

  epoch 1: PASS= 17 FAIL= 2 ABSENT= 1 · 1116.8e9 chu kỳ · 10 blob mạo danh bị loại · calldata 652 B
  epoch 2: PASS= 17 FAIL= 2 ABSENT= 1 · ...
  epoch 3: PASS= 17 FAIL= 2 ABSENT= 1 · ...
```

Ba con số phải đúng, và mỗi con số nói một điều:

| Thấy gì | Nghĩa là |
|---|---|
| `PASS=17 FAIL=2 ABSENT=1` | bốn trạng thái nút đều xuất hiện, mỗi cái do một nguyên nhân khác |
| `10 blob mạo danh bị loại` | lọc theo người ký §J.2.1 đang chạy |
| `calldata 652 B` **ở mọi epoch** | bề mặt on-chain cố định — chính là điều bài báo tuyên bố |

Kết quả ra `results/epochs.csv`, 9 dòng.

### Nếu hỏng

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `ModuleNotFoundError: fastapi` | chỉ ảnh hưởng `provider.api`, không ảnh hưởng `make check` | bỏ qua ở bước này |
| preflight báo XUNG ĐỘT cổng | ai đó chiếm dải 18xxx | `ENGRAM_PORT_ANVIL=19545 ENGRAM_PORT_DAMOCK=19658 make preflight` |
| test `test_spec_consistency` LỖI | mã và đặc tả lệch nhau | **dừng lại**, đừng nới ngưỡng test — đọc thông điệp lỗi, một trong hai bên sai |
| `calldata 0 B` ở một epoch | có ô không được phủ | xem log, kiểm xem worker có bị đình chỉ hàng loạt không |

---

# Bước 2 — Docker, vẫn offline

Bây giờ mới dựng container. Vẫn **không cần mạng ngoài** — dùng `da-mock` thay
Celestia và Anvil thay chuỗi thật.

```bash
cp .env.example .env
docker --version && docker compose version
make build          # ~3 phút lần đầu
make sim
```

`make sim` tự chạy `preflight` trước, nên không khởi động được nếu có xung đột.

> **Bước này KHÔNG deploy hợp đồng.** Bộ mô phỏng chạy trong tiến trình và không
> gọi chuỗi. Deploy chỉ để chứng minh hợp đồng biên dịch và lên chuỗi được, nên
> nó nằm ở profile riêng:
>
> ```bash
> make deploy      # tuỳ chọn — biên dịch + deploy lên anvil trong container
> ```
>
> Số gas — con số thật sự quan trọng — đo ở **bước 3** bằng Foundry trên máy chủ.

### Cần thấy gì

Chín container lên, `orchestrator` chạy xong rồi thoát với mã 0.

```bash
docker compose -p engram-sim ps          # xem trạng thái
docker compose -p engram-sim logs -f     # xem log
curl -s localhost:18101/v1/health        # provider-a
curl -s localhost:18301/v1/health        # aggregator
```

`aggregator` phải trả `"childproof_da_mandatory": true` — tắt cờ đó là mở lại
lỗ §J.2.2.

### Chạy lại lần hai

Container của lần trước vẫn còn. Đó **không phải xung đột** — preflight nhận ra
chúng qua nhãn `com.docker.compose.project` và chỉ báo:

```
  container engram-sim-* (9 cái)                     của lần chạy trước
  ✓ Không xung đột với ai. Còn dấu vết lần chạy trước của CHÍNH MÌNH.
```

`docker compose` tự dựng lại, cứ `make sim` tiếp. Muốn sạch hẳn thì `make down`.

### Dọn

```bash
make down          # CHỈ dọn project engram-sim
```

> **Đừng chạy `docker compose down -v` ở thư mục `~`.** Ở đó có
> `docker-compose.yml.save` của việc khác.

---

# Bước 3 — Foundry, đo gas

Đây là bước cho **con số quan trọng nhất của bài báo**: 487.109 gas.

Cài Foundry vào thư mục riêng để không đụng cài đặt sẵn có:

```bash
export FOUNDRY_DIR="$HOME/engram-sim/.foundry"
curl -L https://foundry.paradigm.xyz | bash
"$FOUNDRY_DIR/bin/foundryup"
export PATH="$FOUNDRY_DIR/bin:$PATH"
forge --version
```

Chạy:

`forge-std` **không nằm trong git** — nó là thư viện ngoài, cài lúc chạy:

```bash
cd ~/engram-sim/chain
forge install foundry-rs/forge-std --no-git
forge build
forge test -vv
forge test --gas-report
```

### Cần thấy gì

Tám test xanh, và trong `--gas-report` một dòng cho `commitEpoch`.

**So với 487.109 trong §K.1.** Nếu lệch:

| Lệch | Nghĩa là |
|---|---|
| Vài trăm gas | bình thường — khác phiên bản solc, khác optimizer runs |
| Vài nghìn | có phép kiểm bị thêm hoặc bớt so với §D.2 — **kiểm lại sáu bước trong `commitEpoch`** |
| Trên 10 % | bố cục public values đã đổi — **đối chiếu `_decodePublicValues` với `clock.py`** |

Ghi con số thật vào bảng §K.1 kèm phiên bản solc và optimizer runs. Đừng để con
số cũ nếu đo được khác.

---

# Bước 4 — Celestia Mocha, light node RIÊNG

Từ đây mới cần mạng. Mục tiêu là những thứ `da-mock` **không tái hiện được**:
rớt mạng, block trễ nhịp, blob không vào được block, và quan trọng nhất — kiểm
rằng đồng thuận Celestia **thật sự áp đặt trường `signer`**, tức nền của §J.2.1.

## Vì sao phải dựng node riêng

`~/celestia-node` đang chạy cho việc khác. Dùng chung thì: khoá của người ta,
số dư của người ta, và nếu họ dừng node giữa chừng thì số đo của bạn đứt mà bạn
không biết vì sao. Bài báo phải mô tả được **node của bạn, khoá của bạn**.

```bash
mkdir -p ~/engram-sim/.celestia
export CELESTIA_HOME="$HOME/engram-sim/.celestia"

docker run --rm -it \
  -v "$CELESTIA_HOME:/home/celestia" \
  ghcr.io/celestiaorg/celestia-node:v0.28.5-mocha \
  celestia light init --p2p.network mocha --node.store /home/celestia
```

Lấy địa chỉ ví và xin TIA ở faucet Mocha:

```bash
docker run --rm -v "$CELESTIA_HOME:/home/celestia" \
  ghcr.io/celestiaorg/celestia-node:v0.28.5-mocha \
  cel-key list --node.type light --p2p.network mocha --keyring-dir /home/celestia/keys
```

Chạy node, **cổng 18659**, không phải 26658:

```bash
docker run -d --name engram-sim-celestia \
  -v "$CELESTIA_HOME:/home/celestia" \
  -p 18659:26658 \
  ghcr.io/celestiaorg/celestia-node:v0.28.5-mocha \
  celestia light start --p2p.network mocha --node.store /home/celestia \
  --rpc.addr 0.0.0.0 --rpc.port 26658
```

Chờ đồng bộ, rồi chạy:

```bash
cd ~/engram-sim
CHAIN_MODE=mocha-anvil CELESTIA_RPC=http://localhost:18659 make sim-mocha
```

## Danh sách kiểm bước 4

Chi tiết ở `docs/KIEM_THU.md` giai đoạn 2. Bốn điều bắt buộc:

- [ ] **Trường `signer` thật khớp địa chỉ đã đăng ký.** Đây là nền của §J.2.1.
      `da-mock` tự điền trường này nên nó không chứng minh được gì.
- [ ] **Nút rớt mạng giữa cửa sổ** → nhận `ABSENT`, không bị phạt nặng, epoch
      sau vẫn chạy tiếp
- [ ] **Cửa sổ *W* không sinh `ABSENT` giả** trong 20 lần chạy liên tiếp. Có thì
      nới *W*, đừng ép nút
- [ ] **Phí DA thật** nằm trong ±20 % con số 0,00024 $

Gây rớt mạng chủ động:

```bash
docker network disconnect engram-sim_engram engram-sim-provider-a-1
sleep 40
docker network connect engram-sim_engram engram-sim-provider-a-1
```

---

# Bước 5 — Blobstream

Bước cuối, và là bước **có thể bỏ qua cho bài hội thảo**. Đọc phần đánh đổi
trước khi quyết.

## Ba lựa chọn

**5-a — Dùng địa chỉ Blobstream canonical trên Sepolia.**
Đây là hạ tầng công cộng, không phải thực thể của người khác trên máy này. Bài
báo trích dẫn địa chỉ và phiên bản. Không tốn gì, và đây là lựa chọn tôi khuyên.

```bash
CHAIN_MODE=mocha-sepolia \
BLOBSTREAM_ADDR=<địa chỉ canonical> \
SEPOLIA_RPC=<RPC của bạn> \
make sim-mocha
```

**5-b — Tự deploy Blobstream.** Cô lập tuyệt đối, nhưng phải chạy operator sinh
bằng chứng SP1 — tốn hàng giờ mỗi lần cập nhật và cần phần cứng mạnh. Với một
bài hội thảo thì chi phí này không đổi lấy được gì thêm.

**5-c — Bỏ qua, ghi thành giới hạn.** Giữ `MockBlobstream`, và viết trong bài:
*"phần chung kết qua Blobstream đã hiện thực và kiểm bằng bộ giả; tích hợp với
Blobstream thật để lại cho công việc sau."* Trung thực, và không ai bắt bẻ được.

## Nếu làm 5-a, kiểm thêm

- [ ] Một epoch đi trọn `Open → Committed → Final`
- [ ] Gas `commitEpoch` trên Sepolia khớp con số Anvil
- [ ] **Cửa sổ epoch thẳng hàng với ranh giới dải nonce.** Nếu vắt qua hai dải
      thì phải chỉnh `H₀` hoặc `L_d` (§D.2.5 ④)
- [ ] Đo độ trễ `Committed → Final`, đối chiếu với chu kỳ cập nhật của Blobstream

---

# Ba thứ **không** bước nào kiểm được

Ghi ra để không ai tưởng đã kiểm rồi. Những điều này phải viết thành giới hạn
trong bài.

**Bằng chứng mật mã thật.** Bản này dùng mô hình chi phí, nên nó **không** chứng
minh Nova/Spartan/SP1 đúng. Nó chứng minh *giao thức xung quanh* đúng.

**Thời gian niêm phong thật.** 1,26 giờ là con số mô hình quy chiếu từ số đo
`sealbench`. Muốn số thật phải chạy `bundle_gen` trên máy đích (§M.2.3 mục 1).

**Hành vi ở quy mô lớn.** 20 hợp đồng không lộ ra vấn đề của 10.000. NFR-05 và
ngưỡng 224 worker (§I.1.7) chỉ kiểm được bằng tính toán, không bằng chạy thử.

---

# Thứ tự làm

Bước 1 hôm nay — nó không đụng gì và cho biết ngay mã có chạy không.

Bước 3 tiếp theo, vì **487.109 gas là con số trung tâm của bài báo** và nó chỉ
cần Foundry, không cần mạng.

Bước 2 khi nào rảnh — Docker chủ yếu để chứng minh kiến trúc dịch vụ tách rời
thật sự chạy được, không sinh số liệu mới.

Bước 4 khi bắt đầu viết phần Đánh giá, vì nó cho những con số **chỉ mạng thật
mới có**.

Bước 5 chọn 5-a hoặc 5-c tuỳ thời gian còn lại.
