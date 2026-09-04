# Engram — hiện thực tham chiếu

Mỗi thư mục là **một hệ thống chạy độc lập**. Khi triển khai thật, một bên chỉ tải
đúng thư mục vai trò của mình.

| Thư mục | Là gì | Ai tải |
|---|---|---|
| `common/` | **thư viện**, không phải dịch vụ | mọi vai trò, qua `pip` |
| `client/` | dịch vụ khách hàng | người thuê lưu trữ |
| `provider/` | dịch vụ nút lưu trữ | người bán dung lượng |
| `worker/` | dịch vụ worker | người chạy SP1 |
| `aggregator/` | dịch vụ aggregator | người gộp và nộp lên EVM |
| `watchtower/` | dịch vụ giám sát | tuỳ chọn |
| `chain/` | hợp đồng Solidity + script deploy | triển khai một lần |
| `adversary/` | **chỉ mô phỏng** — kẻ tấn công | không triển khai thật |
| `orchestrator/` | **chỉ mô phỏng** — dựng kịch bản | không triển khai thật |

Các dịch vụ nói chuyện qua **HTTP**. Không có thư mục chia sẻ, không có tệp trung gian.

## Quy ước comment

    # [SPEC §E.1.4]  truy vết ngược về mục trong đặc tả
    # [CHỐT]         quyết định đã chốt trong thiết kế
    # [ĐO]           hằng số có số đo, kèm nguồn
    # [MỞ]           chưa quyết, cần bàn trước khi dựa vào

## Chạy mô phỏng

    make sim          # dựng toàn bộ dịch vụ + chạy kịch bản KB-01..KB-07
    make sim-attack   # chạy kèm adversary, xuất bảng so sánh có/không bản sửa

## Chạy nhanh, không cần Docker

    make run          # mô phỏng trong tiến trình, ~2 giây
    make test-py      # ba bộ test

`make run` chạy toàn bộ bốn tầng trong một tiến trình Python: nút sinh bundle →
đăng lên DA trong bộ nhớ → worker lọc và xác minh → aggregator gộp và tính
public values 296 byte. Kèm sẵn kẻ tấn công mạo danh blob và ba trạng thái nút.

Kết quả ra `results/epochs.csv`, và bảng đối chiếu với các con số trong đặc tả.

## Chạy đầy đủ với Docker

    make build && make sim

Xem `docs/KIEM_THU.md` — **ba giai đoạn, không nhảy cóc**. Giai đoạn 2 chuyển
sang Celestia Mocha là **bắt buộc**: chỉ ở đó mới kiểm được rớt mạng, block trễ
nhịp, và quan trọng nhất là việc đồng thuận Celestia thật sự áp đặt trường
`signer` — nền của §J.2.1.

## Chạy trên máy chủ dùng chung

`node-blockchain` đang chạy celestia-node, sp1-blobstream, orchestrator-relayer,
nitro/orbit và các stack dal-*. **Giải nén thành `~/engram-sim`, KHÔNG phải
`~/engram`** — thư mục đó đã có repo cũ.

    make preflight    # kiểm cổng, container, đĩa, RAM  ← chạy trước tiên

Chi tiết ở `docs/KIEM_THU.md` phụ lục.

## Lệnh

    make preflight    # kiểm xung đột trên máy chung
    make check        # đối chiếu mã ↔ đặc tả, rồi chạy thử  ← chạy cái này trước
    make run          # mô phỏng trong tiến trình, ~2 giây
    make test-py      # bốn bộ test
    make build && make sim    # đầy đủ với Docker
    make gas          # đo gas hợp đồng, đối chiếu 487.109

## Đối chiếu mã với đặc tả

`common/tests/test_spec_consistency.py` kiểm 13 con số mà bài báo tuyên bố phải
khớp với thứ mã tính ra. Nó tồn tại vì trong quá trình làm, **bốn** lần mã và
đặc tả lệch nhau mà không ai phát hiện cho tới lúc ngồi đo:

| # | Lỗi | Hậu quả |
|---|---|---|
| ① | fan-in `(i·a+b) % i` luôn trả cùng vị trí | bậc 6 trên giấy, bậc 1 thực tế |
| ② | bao đóng phụ thuộc "phủ hết" | đo được 23,9 % |
| ③ | bảng kinh tế dùng 2,1 GHz thay vì 3,8 GHz | lệch 1,8 lần mọi biên |
| ④ | `assigned_count or {}` bỏ dict rỗng | trần khe im lặng ngừng hoạt động |

Cả bốn đều "đúng trên giấy, sai khi chạy". Khi một con số đổi, **phải sửa cả hai
bên** — không được nới ngưỡng test cho khớp.
