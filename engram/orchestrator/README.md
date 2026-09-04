# orchestrator — CHỈ DÙNG KHI MÔ PHỎNG

Không triển khai thật. Dựng N tiến trình dịch vụ, chạy kịch bản KB-01..KB-07 của
[SPEC §L], thu số liệu ra CSV.

    python -m orchestrator --profile sim --deals 20 --epochs 3
    python -m orchestrator --profile sim --deals 20 --epochs 3 --with-adversary
