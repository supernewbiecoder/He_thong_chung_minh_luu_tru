# Engram SP1 — một gói cho `execute` và `prove`

## Kết luận thiết kế

`execute` và `prove` dùng chung:

- một `engram-host` binary;
- một `engram-guest` ELF;
- `GuestInput`, `ProofBundle` và `PublicValues`;
- bundle/VK cache trong `results/artifacts`;
- một `results/results.jsonl`;
- cùng analyzer và quy tắc hợp lệ `num_verified == batch`, public values 256 byte.

Khác nhau chỉ ở backend và profile tài nguyên:

| Chế độ | SP1 API | Đầu ra | Profile mặc định |
|---|---|---|---|
| `execute` | `client.execute(...).run()` | cycles, prover gas, time, RAM, public values | 22 GiB RAM, 8 GiB shm, 4 CPU |
| `prove` | `client.prove(...).groth16().run()` | proof, public values, vkey, time, RAM | 28 GiB container, chỉ chạy khi bật rõ ràng |

`run_execute_today.sh` vẫn được giữ vì nó là runner chuyên dụng, an toàn cho máy chỉ
còn khoảng 27 GiB RAM. `run_sp1.sh` là entrypoint thống nhất ở phía ngoài.

## 1. Build một image duy nhất

```bash
unzip Engram-simulation-v3.2-unified.zip
cd simulation

chmod +x \
  sp1_verify/sweep.sh \
  sp1_verify/run_execute_today.sh \
  sp1_verify/run_sp1.sh \
  experiments/run.sh

./sp1_verify/run_sp1.sh build
```

Dockerfile build cả Guest ELF và Host một lần. Không có image execute riêng và image
prove riêng.

## 2. Chạy benchmark `execute` trên server hiện tại

```bash
tmux new -s engram

DOCKER_MEM=22g \
DOCKER_SHM=8g \
DOCKER_CPUS=4 \
MIN_AVAILABLE_GIB=24 \
REPLICATES=3 \
BATCH_POINTS="1 2" \
CHALLENGE_POINTS="4 16" \
RUN_DISTINCT=1 \
./sp1_verify/run_sp1.sh execute \
2>&1 | tee results/host_execute.log
```

Lệnh này không thể rơi sang `prove`: runner gọi đúng các phase `prepare`, `point` và
`distinct`, không gọi phase `prove`.

## 3. Chạy Groth16 sau này bằng chính image đó

Trên máy hiện chỉ còn 27 GiB khả dụng, runner mặc định từ chối prove vì ngưỡng là
32 GiB. Khi có đủ RAM, chạy điểm N=1 trước:

```bash
ENABLE_PROVE=1 \
MIN_PROVE_AVAILABLE_GIB=32 \
DOCKER_MEM_PROVE=28g \
DOCKER_SHM_PROVE=8g \
DOCKER_CPUS_PROVE=8 \
PROVE_BATCH_POINTS="1" \
PROVE_CHALLENGES=1 \
PROVE_TREE_HEIGHT=4 \
./sp1_verify/run_sp1.sh prove \
2>&1 | tee results/host_prove.log
```

Proof hợp lệ được lưu tại:

```text
results/artifacts/groth16_batch1_<run_id>/
├── proof.bin
├── public_values.bin
├── vkey.txt
├── cfg.json
└── result.json
```

`result.json` và dòng tương ứng trong `results.jsonl` chỉ có `ok=true` khi:

- SP1 verify proof thành công;
- `num_verified == batch`;
- public values đúng 256 byte và parse đúng bố cục.

Analyzer bỏ mọi proof có `ok != true`, nên artifact chẩn đoán không thể bị dùng nhầm
làm kết quả paper.

## 4. Pipeline chung

Chạy execute trước, chưa prove:

```bash
./sp1_verify/run_sp1.sh pipeline
```

Chạy execute rồi prove trong cùng pipeline khi có đủ tài nguyên:

```bash
ENABLE_PROVE=1 ./sp1_verify/run_sp1.sh pipeline
```

## 5. Tổng hợp chung

```bash
./sp1_verify/run_sp1.sh analyze
```

Analyzer đọc cả execute và prove trong cùng JSONL nhưng tách metric theo `mode`.

## Lưu ý về máy 27 GiB

Tích hợp code không có nghĩa là phải chạy prove hôm nay. Với server hiện tại, nên hoàn
thành ma trận execute trước. Cờ `ALLOW_LOW_MEMORY_PROVE=1` tồn tại để chạy thử có chủ
đích, nhưng có rủi ro OOM và không được bật trong lệnh benchmark mặc định.
