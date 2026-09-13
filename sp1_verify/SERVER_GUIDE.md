# 🖥️ Hướng dẫn chạy trên SERVER DÙNG CHUNG — an toàn & cô lập

> Viết cho server dùng chung: mọi thứ cô lập trong container, KHÔNG đụng tài nguyên chung,
> KHÔNG cần quyền root host, KHÔNG docker.sock.

> **Server hiện chỉ còn khoảng 27 GiB RAM khả dụng:** dùng
> [`RUN_TODAY_27GB.md`](RUN_TODAY_27GB.md) và `run_execute_today.sh`. Các ví dụ
> `--memory=32g` bên dưới chỉ dùng khi máy thực sự còn hơn 35 GiB khả dụng.

> **Bản này sửa 2 lỗi khiến lệnh cũ chết ngay:** (a) thiếu `chmod 777 results` → container
> uid 10001 không ghi được vào bind mount; (b) `--read-only` mà không mount
> `/home/runner/.sp1` → sp1-sdk không ghi được cache. `sweep.sh` giờ có preflight bắt cả
> hai trong 5 giây đầu và in đúng lệnh sửa, nhưng tốt nhất là làm đúng từ đầu.

---

## 0. Cam kết an toàn — container này làm gì / KHÔNG làm gì

| Khía cạnh | Đảm bảo |
|---|---|
| Ghi file | CHỈ ghi vào `results/` bạn mount + tmpfs trong RAM của container |
| Quyền | Chạy bằng user không phải root (`runner`, uid 10001) |
| Mạng (execute) | `--execute` KHÔNG cần mạng — chạy offline hoàn toàn |
| docker.sock | KHÔNG dùng. (Docker-in-Docker = trao root host, đã loại bỏ) |
| Tài nguyên | Giới hạn RAM/CPU bằng `--memory`/`--cpus` (mục 4) |
| Dọn dẹp | `--rm` tự xóa container sau khi chạy |

**Quan trọng:** giai đoạn hiện tại (`--execute` đếm cycles) là an toàn nhất — không mạng,
không Docker lồng, không root. Đây là thứ nên chạy trên server dùng chung.

---

## 1. Kiểm tra trước (một lần)

```bash
ssh user@server
docker --version
docker run --rm hello-world     # bạn có quyền chạy container không
nproc && free -h && df -h ~     # CPU / RAM / đĩa trống
```

`permission denied` → bạn chưa ở nhóm `docker`, hỏi admin (hoặc dùng `podman`, lệnh gần
như y hệt).

**Đĩa:** `--tree-height 23` (sector 32GB) cần ~32GB trống ở `SCRATCH_DIR` trong lúc seal.
File sector tạm bị xoá ngay sau khi thu challenge, nhưng phải có chỗ trong lúc đó.

---

## 2. Đưa code lên server

**Cách A — build image ngay trên server:**
```bash
# ở máy bạn
cd simulation
tar czf engram.tar.gz --exclude='target' --exclude='*/target' \
    --exclude='results' --exclude='mockdata' .
scp engram.tar.gz user@server:~/

# trên server
ssh user@server
mkdir -p ~/engram && cd ~/engram
tar xzf ~/engram.tar.gz
docker build -t engram-sp1-$USER .        # ~15-25 phút (có build guest ELF riscv32)
```

**Cách B — build ở máy bạn rồi đẩy image** (dùng khi server chặn `sp1up.succinct.xyz`,
đây là lỗi hay gặp nhất ở bước build):
```bash
docker build -t engram-sp1-$USER .
docker save engram-sp1-$USER | gzip > engram-img.tar.gz
scp engram-img.tar.gz user@server:~/
ssh user@server 'gunzip -c ~/engram-img.tar.gz | docker load'
```

> Tên image kèm `$USER` để không trùng image người khác trên server dùng chung.

### 2b. Lấy Cargo.lock ra để commit (làm MỘT LẦN, quan trọng cho paper)

Build đầu tiên resolve dependency tự do. Lấy lock ra, commit vào repo, rồi từ đó build
bằng `--locked` — số liệu trong paper mới gắn được với một cây dependency xác định:
```bash
mkdir -p results && chmod 777 results
docker run --rm -v "$(pwd)/results:/results" \
    --entrypoint sh engram-sp1-$USER -c 'cp /work/locks/* /results/'
ls results/*.Cargo.lock      # bundle_gen / host / guest
# → mang về, đặt đúng chỗ (sp1_verify/{bundle_gen,host,guest}/Cargo.lock), git commit
# → lần sau: docker build --build-arg LOCKED=--locked -t engram-sp1-$USER .
```

---

## 3. Chuẩn bị thư mục kết quả (BẮT BUỘC — bước hay bị bỏ)

```bash
cd ~/engram
mkdir -p results && chmod 777 results
```

Container chạy bằng uid 10001; bind mount giữ nguyên ownership của host, nên nếu
`results/` thuộc uid của bạn với mode 755 thì container **không ghi được** và cả sweep
chết ở dòng đầu. `chmod 777` là cách đơn giản nhất trên máy dùng chung.

---

## 4. Chạy — luôn trong `screen`/`tmux`

### Phase 0 — SMOKE (cổng chặn, ~5 phút)
```bash
screen -S engram

docker run --rm \
    --read-only --tmpfs /tmp \
    --tmpfs /home/runner/.sp1:exec,size=2g \
    --shm-size=8g --memory=16g --cpus=4 \
    -v "$(pwd)/results:/results" \
    engram-sp1-$USER smoke
```
`Ctrl-A` rồi `D` để tách; `screen -r engram` để quay lại.

Xem dòng `TỔNG CYCLES`:
- **< 100 triệu** → tốt, quét thoải mái
- **100M – 1 tỷ** → bình thường, prove sẽ lâu
- **> 1 tỷ** → prove có thể OOM/rất lâu; xem MEASUREMENT_STRATEGY.md mục 5

Giải thích các flag:
- `--rm` — xoá container sau khi xong.
- `--read-only` — rootfs chỉ đọc, container không sửa được gì trong image.
- `--tmpfs /tmp` — `/tmp` là RAM riêng của container.
- `--tmpfs /home/runner/.sp1:exec,size=2g` — **BẮT BUỘC khi có `--read-only`**: sp1-sdk
  ghi cache vào `$HOME/.sp1`, mà `$HOME` nằm trên rootfs chỉ đọc. `exec` cần cho các
  binary phụ SP1 gọi từ đây.
- `--memory` / `--cpus` — không giành tài nguyên của người khác.
- `-v .../results:/results` — CHỖ DUY NHẤT container ghi ra host.

### Phase 1 — EXECUTE SWEEP (rẻ, ~30–60 phút) ← MỤC TIÊU CHÍNH
```bash
docker run --rm --read-only --tmpfs /tmp \
    --tmpfs /home/runner/.sp1:exec,size=2g \
    --shm-size=8g --memory=32g --cpus=8 \
    -v "$(pwd)/results:/results" \
    engram-sp1-$USER execute
```

Quét config **thật** (sector 32GB) — cần đĩa, nên dùng volume riêng cho scratch:
```bash
mkdir -p scratch && chmod 777 scratch
docker run --rm --tmpfs /tmp \
    --tmpfs /home/runner/.sp1:exec,size=2g \
    --shm-size=8g --memory=32g --cpus=8 \
    -e TREE_HEIGHT=23 -e CHALLENGES_FIXED=50 \
    -e BATCH_EXECUTE="1 2 5 10 25 50" \
    -e SCRATCH_DIR=/scratch \
    -v "$(pwd)/results:/results" -v "$(pwd)/scratch:/scratch" \
    engram-sp1-$USER execute
```
(Bỏ `--read-only` ở đây vì bind mount thêm; nếu muốn giữ thì vẫn được, `/scratch` là
mount nên ghi được.)

### Phase 1c — ĐỐI CHỨNG (nên chạy, ~15 phút ở h nhỏ)
```bash
docker run --rm --read-only --tmpfs /tmp \
    --tmpfs /home/runner/.sp1:exec,size=2g \
    --shm-size=8g --memory=32g --cpus=8 -e DISTINCT_N=5 \
    -v "$(pwd)/results:/results" engram-sp1-$USER distinct
```
Sinh 5 bundle **phân biệt** và so cycles với 5 **bản sao**. Đây là bằng chứng cho ghi chú
đo đạc trong paper — reviewer sẽ hỏi chính xác câu này.

### Phase 2+3 — LOCAL PROVE (tùy chọn)
Groth16 local cần nhiều RAM/disk. Chỉ chạy trên máy riêng đã cô lập; hosted prover
và khóa dịch vụ không được hỗ trợ trong repository simulation-only. Nếu thiếu tài
nguyên, giữ số execute/cycles và ghi proof latency là "chưa đo".

---

## 5. Lấy kết quả về & dọn dẹp

```bash
scp -r user@server:~/engram/results ./
# ở máy bạn:
python3 simulation/sp1_verify/analyze.py results/results.jsonl --outdir analysis
```

Trong `results/`:
- `results.jsonl` — mỗi dòng 1 điểm đo, có `run_id` + `phase` + `cfg` (tree_height,
  sector_size…) nên nhiều lượt sweep không lẫn vào nhau.
- `sweep_<run_id>.log` — log đầy đủ.
- `artifacts/h<h>_c<c>/` — bundle cache (giữ lại để chạy lại không phải sinh proof lần nữa).
- `artifacts/groth16_batchN_<run_id>/` — proof + public_values + vkey + cfg cho bước EVM.

Dọn:
```bash
ssh user@server
docker rmi engram-sp1-$USER
rm -rf ~/engram ~/engram.tar.gz ~/engram-img.tar.gz
docker image prune -f
screen -X -S engram quit
```

---

## 6. Xử lý sự cố

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `KHÔNG ghi được vào /results` | bind mount thuộc uid khác | `chmod 777 results` (mục 3) |
| `KHÔNG ghi được vào $HOME/.sp1` | `--read-only` + `$HOME` trên rootfs | thêm `--tmpfs /home/runner/.sp1:exec,size=2g` |
| `permission denied` khi docker run | chưa ở nhóm docker | hỏi admin, hoặc `podman` |
| Smoke `Killed` | container hết RAM | tăng `--memory`; xem `RAM peak` ở dòng TÓM TẮT |
| Build lỗi ở `sp1up` | server chặn sp1up.succinct.xyz | build ở máy bạn rồi đẩy image (Cách B) |
| `Unrecognized option: remap-path-scope` | toolchain SP1 lệch crate | Dockerfile đã pin `SP1_VERSION=v6.3.1`; đừng bỏ pin |
| `bundle.bin hỏng hoặc lệch version nova` | bundle_gen ≠ guest resolve khác nova | commit Cargo.lock, build `--locked` (mục 2b) |
| Cycles quá lớn (>1 tỷ) | bài toán nặng | MEASUREMENT_STRATEGY.md mục 5 (pivot) |
| Hết đĩa lúc seal | `TREE_HEIGHT` lớn | dùng `-e SCRATCH_DIR=/scratch` + volume riêng |
| Rớt SSH mất tiến trình | không dùng screen | luôn `screen -S engram` |

---

## 7. Tóm tắt lệnh (copy-paste)

```bash
# --- một lần: đưa lên + build ---
cd simulation && tar czf engram.tar.gz --exclude='target' --exclude='*/target' \
    --exclude='results' --exclude='mockdata' .
scp engram.tar.gz user@server:~/
ssh user@server
mkdir -p ~/engram && cd ~/engram && tar xzf ~/engram.tar.gz
docker build -t engram-sp1-$USER .
mkdir -p results && chmod 777 results

# --- chạy trong screen ---
screen -S engram
RUNFLAGS='--rm --read-only --tmpfs /tmp --tmpfs /home/runner/.sp1:exec,size=2g --shm-size=8g'
docker run $RUNFLAGS --memory=16g --cpus=4 -v "$(pwd)/results:/results" \
    engram-sp1-$USER smoke
# nếu smoke pass:
docker run $RUNFLAGS --memory=32g --cpus=8 -v "$(pwd)/results:/results" \
    engram-sp1-$USER execute
docker run $RUNFLAGS --memory=32g --cpus=8 -v "$(pwd)/results:/results" \
    engram-sp1-$USER distinct

# --- lấy về + dọn ---
# (máy bạn) scp -r user@server:~/engram/results ./
# (máy bạn) python3 simulation/sp1_verify/analyze.py results/results.jsonl --outdir analysis
# (server)  docker rmi engram-sp1-$USER && rm -rf ~/engram*
```
