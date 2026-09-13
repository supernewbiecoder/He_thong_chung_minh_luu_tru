# Chạy toàn bộ benchmark khả thi hôm nay — server còn ~27 GiB RAM

Mục tiêu của runbook này là lấy **SP1 execute thật** (cycles, prover gas, thời
gian, throughput, peak RSS và peak RAM cgroup), không sinh Groth16. Cấu hình
mặc định chỉ cấp 22 GiB cho container để chừa khoảng 5 GiB cho host/tác vụ khác.

## 1. Đúng phiên bản

Dùng ZIP `Engram-simulation-v3.1-execute-ready.zip`, không dùng
`simulation(1).zip` 215 KB cũ.

```bash
unzip Engram-simulation-v3.1-execute-ready.zip
cd simulation
chmod +x sp1_verify/sweep.sh sp1_verify/run_execute_today.sh experiments/run.sh
```

## 2. Kiểm tra server

```bash
nproc
free -h
df -h .
docker --version
grep -m1 -E 'model name|Hardware' /proc/cpuinfo
grep -m1 -oE 'avx2|avx512f' /proc/cpuinfo
```

Với `TREE_HEIGHT=4`, không cần sector 32 GB trên đĩa. Không chuyển sang
`TREE_HEIGHT=23` trong ngày cuối nếu chưa có ít nhất 40 GB scratch trống và chưa
đo h=4 thành công; bước tạo sector 32 GB là một thí nghiệm khác với SP1 execute.

## 3. Build image đúng SP1 6.3.1

```bash
docker build --pull -t engram-sp1-$USER .
```

Build có thể mất 15–30 phút vì nó build Guest ELF RISC-V. Runtime execute sau
đó chạy offline (`--network none`). Giữ nguyên image cho mọi replicate.

Ghi checksum source/image vào log nghiên cứu:

```bash
sha256sum sp1_verify/host/src/main.rs sp1_verify/guest/src/main.rs \
  sp1_verify/shared/src/lib.rs | tee source_sha256.txt
docker image inspect engram-sp1-$USER \
  --format '{{.Id}} {{.Created}}' | tee image_id.txt

mkdir -p results && chmod 777 results
docker run --rm --entrypoint sh -v "$(pwd)/results:/results" \
  engram-sp1-$USER -c 'cp /work/locks/* /results/'
sha256sum results/*.Cargo.lock | tee dependency_locks_sha256.txt
```

## 4. Một điểm kiểm tra trước

Chạy trong `tmux`/`screen`. Lệnh này chỉ đo `batch=1, challenges=1` một lần:

```bash
tmux new -s engram

IMAGE=engram-sp1-$USER \
DOCKER_MEM=22g DOCKER_SHM=8g DOCKER_CPUS=4 \
MIN_AVAILABLE_GIB=24 REPLICATES=1 \
BATCH_POINTS="1" CHALLENGE_POINTS="" RUN_DISTINCT=0 \
./sp1_verify/run_execute_today.sh 2>&1 | tee results/host_smoke.log
```

Điểm chỉ hợp lệ khi JSON có đồng thời:

- `"ok": true`
- `num_verified == batch`
- `pv_bytes == 256`
- `cycles > 0`
- `prover_gas > 0`

Kiểm ngay:

```bash
jq -c 'select(.mode=="execute") |
  {run_id,ok,batch,challenges,cycles,prover_gas,execute_s,
   throughput_mcycles_s,cgroup_memory_peak_bytes,num_verified,pv_bytes}' \
  results/results.jsonl | tail -n 5
```

Không chạy full nếu dòng cuối không `ok=true` hoặc container bị exit 137.

## 5. Ma trận chính — 12 execute thật + 1 đối chứng

Ma trận mặc định:

- batch ∈ {1, 2}, challenges=1, mỗi điểm 3 replicate;
- batch=1, challenges ∈ {4, 16}, mỗi điểm 3 replicate;
- đối chứng N=2: hai bundle phân biệt dùng chung VK so với hai bản sao.

Với số cũ N=1 khoảng 804 giây, dự kiến tổng thời gian là vài giờ, không phải vài
phút. Script kiểm `MemAvailable` trước từng điểm, mỗi điểm chạy trong container
riêng và fsync JSONL ngay khi xong.

```bash
IMAGE=engram-sp1-$USER \
DOCKER_MEM=22g DOCKER_SHM=8g DOCKER_CPUS=4 \
MIN_AVAILABLE_GIB=24 REPLICATES=3 \
TREE_HEIGHT=4 FIXED_CHALLENGES=1 \
BATCH_POINTS="1 2" CHALLENGE_POINTS="4 16" \
RUN_DISTINCT=1 DISTINCT_N=2 \
./sp1_verify/run_execute_today.sh 2>&1 | tee results/host_full.log
```

Tách tmux: `Ctrl-B`, rồi `D`. Vào lại: `tmux attach -t engram`.

Nếu N=2 OOM, script không thử batch lớn hơn nhưng vẫn tiếp tục các điểm batch=1.
Không tăng `DOCKER_MEM` quá 22g khi host chỉ còn 27g khả dụng.

## 6. Điểm mở rộng (chỉ khi N=2 an toàn)

Xem peak N=2:

```bash
jq -r 'select(.mode=="execute" and .ok==true and .batch==2) |
  [.run_id,.execute_s,(.cgroup_memory_peak_bytes/1073741824)] | @tsv' \
  results/results.jsonl
```

Chỉ thử N=3 nếu **mọi** replicate N=2 dưới 18 GiB cgroup peak và host vẫn còn
ít nhất 24 GiB `MemAvailable`. Chạy một replicate trước:

```bash
IMAGE=engram-sp1-$USER \
DOCKER_MEM=22g DOCKER_SHM=8g DOCKER_CPUS=4 \
MIN_AVAILABLE_GIB=24 REPLICATES=1 \
BATCH_POINTS="" EXTRA_BATCH_POINTS="3" CHALLENGE_POINTS="" \
RUN_DISTINCT=0 TREE_HEIGHT=4 FIXED_CHALLENGES=1 \
./sp1_verify/run_execute_today.sh 2>&1 | tee results/host_n3.log
```

Không thử N=4+ trên 27 GiB trước khi N=3 có peak rõ ràng dưới 18 GiB.

## 7. Phân tích replicate

```bash
python3 sp1_verify/analyze.py results/results.jsonl --outdir results/analysis

sed -n '1,240p' results/analysis/table_execute_replicates.md
column -s, -t < results/analysis/execute_replicates.csv | less -S
```

Hai file chính:

- `results/analysis/execute_replicates.csv`: mean/std/max, không vứt replicate.
- `results/analysis/table_execute_replicates.md`: bảng dán vào báo cáo.

Lưu toàn bộ `results/`, `source_sha256.txt`, `image_id.txt`, output `free -h`,
`nproc`, CPU model và câu lệnh đã chạy. Không chỉ lưu bảng tổng hợp.

## 8. Các benchmark không cần Groth16

Chạy sau hoặc song song trên máy khác; chúng nhẹ hơn SP1 execute.

```bash
# 32/32 invariant/security tests
python3 -m unittest \
  experiments.system_sim.test_system_sim \
  experiments.system_sim.test_program_identity -v

# System simulator: full matrix, 20 replicate/cấu hình (khoảng 1.000 runs)
python3 -m experiments.system_sim.bench_system \
  --mode full --suite all --replicates 20 --seed 20260809 \
  --out-dir results/system_v3_1

# DA packing/spec cost model, không gửi Celestia public RPC
DA_DRY_RUN=1 python3 experiments/l2_da/bench_da.py --mode full

# EVM contract/root-commit gas trên Anvil local bằng MockVerifier
# (cần forge + anvil; đây KHÔNG phải gas của SP1 Groth16 verifier thật)
python3 experiments/l4_evm/bench_evm.py --mode full

# Gom bảng
python3 experiments/analyze/make_tables.py --out results/tables_v3_1.md
```

## 9. Phạm vi kết luận hợp lệ

SP1 execute thật trả lời tốt phần off-chain của RQ3: cycles, prover gas, thời
gian execute và RAM tăng thế nào theo batch/challenges. Nó cũng kiểm Guest thật
đã verify đủ Nova/Spartan bundles.

Nó **không** sinh proof, nên không đo được `prove_s`, kích thước Groth16 thực tế
hay gas SP1 verifier thật. Vì vậy:

- RQ1: vẫn chỉ có phân tích/DA measurement cho mức giảm dữ liệu on-chain;
- RQ2: MockVerifier/contract gas chỉ là contract overhead, chưa chứng minh gas
  verifier Groth16 thật gần hằng số;
- RQ3: được trả lời thực nghiệm ở phần execute/off-chain, chưa có proving time.

Trong báo cáo, ghi đúng nhãn: **SP1 execute measurement**, không gọi là
**SP1 proving benchmark**.
