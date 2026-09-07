# ═══════════════════════════════════════════════════════════════════════════
#  Engram — lệnh thường dùng
#  [CHỐT A1-b · A2-c · A3-a · C3-a]
# ═══════════════════════════════════════════════════════════════════════════
.PHONY: preflight help build sim deploy reset check-sol baselines attacks gas sim-mocha down logs test test-py test-sol gas clean fmt

CHAIN_MODE ?= local
export DOCKER_UID := $(shell id -u)
export DOCKER_GID := $(shell id -g)
N_DEALS    ?= 20
N_EPOCHS   ?= 3
N_SHARDS   ?= 2

preflight:       ## Kiểm xung đột cổng/container TRƯỚC khi chạy trên máy chung
	@bash scripts/preflight.sh

help:            ## Danh sách lệnh
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

build:           ## Xây mọi ảnh Docker
	docker compose build

# `--build` là BẮT BUỘC, không phải tuỳ chọn.
#
# Thiếu nó thì sau `git pull` container vẫn chạy MÃ CŨ trong ảnh đã dựng, và
# mọi bản sửa trông như không có tác dụng. Triệu chứng đặc trưng: traceback trỏ
# vào số dòng KHÔNG khớp với tệp trên đĩa, và thông điệp lỗi mới không in ra.
#
# `mkdir -p results` để thư mục tồn tại và thuộc người gọi TRƯỚC khi Docker
# mount. Nếu để Docker tự tạo, nó tạo bằng root và bind mount thành chỉ-đọc với
# uid trong container.
sim: preflight   ## Chạy mô phỏng, chế độ local (không cần mạng ngoài)
	@mkdir -p results
	CHAIN_MODE=local N_DEALS=$(N_DEALS) N_EPOCHS=$(N_EPOCHS) \
	docker compose --profile local up --build --abort-on-container-exit orchestrator

deploy:          ## Biên dịch và deploy hợp đồng lên anvil trong container
	docker compose --profile local --profile chain up --abort-on-container-exit deployer

sim-mocha:       ## Chạy trên Celestia Mocha + Anvil
	@mkdir -p results
	CHAIN_MODE=mocha-anvil docker compose up --build --abort-on-container-exit orchestrator

reset:           ## Dọn sạch rồi chạy lại từ đầu
	-docker compose --profile local --profile chain down -v --remove-orphans
	@$(MAKE) --no-print-directory sim

down:            ## Dừng và dọn
	docker compose --profile local --profile chain down -v --remove-orphans

logs:            ## Xem log mọi dịch vụ
	docker compose logs -f

test: test-py test-sol  ## Chạy toàn bộ test

PYPATH = common/src:provider/src:worker/src:aggregator/src:client/src:orchestrator/src

test-py:         ## Test Python, không cần Docker
	@for t in common/tests/test_spec_consistency.py \
	          common/tests/test_blob_impersonation.py \
	          common/tests/test_membership.py \
	          provider/tests/test_fanin_closure.py \
	          worker/tests/test_lottery.py \
	          aggregator/tests/test_circuit_breaker.py; do \
	  printf "  %-46s" "$$t"; \
	  PYTHONPATH=$(PYPATH) python3 $$t >/dev/null 2>&1 && echo "OK" || { echo "LỖI"; exit 1; }; \
	done

check: test-py   ## Đối chiếu mã với đặc tả rồi chạy thử
	@echo
	@$(MAKE) --no-print-directory run

# N_SHARDS PHẢI truyền xuống, không ghim cứng.
#
# Bản trước ghi `--shards 2` cố định, nên `make run N_SHARDS=4` chạy im lặng với
# 2 mảnh. Phép quét mảnh cho ra ba lần chạy GIỐNG HỆT NHAU mà không báo gì —
# loại hỏng tệ nhất, vì nó trông như đã có dữ liệu.
run:             ## Chạy mô phỏng TRONG TIẾN TRÌNH — không cần Docker, không cần mạng
	PYTHONPATH=$(PYPATH) python3 -m orchestrator \
		--deals $(N_DEALS) --epochs $(N_EPOCHS) --shards $(N_SHARDS)

check-sol:       ## Kiểm chuỗi Solidity chỉ dùng ASCII
	@python3 chain/check_ascii.py

test-sol: check-sol  ## Test hợp đồng
	cd chain && forge test -vv

gas:             ## Đo gas commitEpoch, đối chiếu §K.1
	cd chain && forge test --match-test "gas_" -vv

baselines:       ## SO SÁNH 4 phương án theo batch — bảng chính phần Evaluation
	cd chain && forge test --match-contract BaselinesTest -vv

attacks:         ## Bảng tấn công bị chặn — số liệu RQ1
	@$(MAKE) --no-print-directory test-py
	cd chain && forge test --match-contract EngramManagerTest -vv

fmt:             ## Định dạng mã
	cd chain && forge fmt

clean:
	rm -rf chain/out chain/cache results/*.csv
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
