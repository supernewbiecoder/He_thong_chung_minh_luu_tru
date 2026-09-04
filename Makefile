# ═══════════════════════════════════════════════════════════════════════════
#  Engram — lệnh thường dùng
#  [CHỐT A1-b · A2-c · A3-a · C3-a]
# ═══════════════════════════════════════════════════════════════════════════
.PHONY: preflight help build sim deploy sim-mocha down logs test test-py test-sol gas clean fmt

CHAIN_MODE ?= local
N_DEALS    ?= 20
N_EPOCHS   ?= 3

preflight:       ## Kiểm xung đột cổng/container TRƯỚC khi chạy trên máy chung
	@bash scripts/preflight.sh

help:            ## Danh sách lệnh
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

build:           ## Xây mọi ảnh Docker
	docker compose build

sim: preflight   ## Chạy mô phỏng, chế độ local (không cần mạng ngoài)
	CHAIN_MODE=local N_DEALS=$(N_DEALS) N_EPOCHS=$(N_EPOCHS) \
	docker compose --profile local up --abort-on-container-exit orchestrator

deploy:          ## Biên dịch và deploy hợp đồng lên anvil trong container
	docker compose --profile local --profile chain up --abort-on-container-exit deployer

sim-mocha:       ## Chạy trên Celestia Mocha + Anvil
	CHAIN_MODE=mocha-anvil docker compose up --abort-on-container-exit orchestrator

down:            ## Dừng và dọn
	docker compose --profile local down -v

logs:            ## Xem log mọi dịch vụ
	docker compose logs -f

test: test-py test-sol  ## Chạy toàn bộ test

PYPATH = common/src:provider/src:worker/src:aggregator/src:client/src:orchestrator/src

test-py:         ## Test Python, không cần Docker
	@for t in common/tests/test_spec_consistency.py \
	          common/tests/test_blob_impersonation.py \
	          provider/tests/test_fanin_closure.py \
	          worker/tests/test_lottery.py; do \
	  printf "  %-46s" "$$t"; \
	  PYTHONPATH=$(PYPATH) python3 $$t >/dev/null 2>&1 && echo "OK" || { echo "LỖI"; exit 1; }; \
	done

check: test-py   ## Đối chiếu mã với đặc tả rồi chạy thử
	@echo
	@$(MAKE) --no-print-directory run

run:             ## Chạy mô phỏng TRONG TIẾN TRÌNH — không cần Docker, không cần mạng
	PYTHONPATH=$(PYPATH) python3 -m orchestrator \
		--deals $(N_DEALS) --epochs $(N_EPOCHS) --shards 2

test-sol:        ## Test hợp đồng
	cd chain && forge test -vv

gas:             ## Đo gas, đối chiếu 487.109 trong §K.1
	cd chain && forge test --gas-report

fmt:             ## Định dạng mã
	cd chain && forge fmt

clean:
	rm -rf chain/out chain/cache results/*.csv
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
