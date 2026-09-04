# da-mock — CHỈ DÙNG KHI MÔ PHỎNG

Hiện thực tập con API blob của Celestia, giữ trong bộ nhớ, để giai đoạn 1 của
`docs/KIEM_THU.md` chạy **hoàn toàn không cần mạng**.

## Nó tái hiện được gì

- Namespace mở: ai cũng ghi vào được — đúng như Celestia
- Share phiên bản 1 có trường `signer` 20 byte
- Chiều cao block tăng đều, dùng làm đồng hồ của hệ
- Phí và số share tính theo đúng công thức thật

## Nó KHÔNG tái hiện được gì

Và đây là lý do **phải** chuyển sang Mocha ở giai đoạn 2:

- Rớt mạng, block trễ nhịp, blob không vào được block
- Mempool đầy, phí biến động
- **Việc đồng thuận Celestia thật sự áp đặt trường `signer`** — mock tự điền,
  nên nó không chứng minh được nền của §J.2.1

Xem `docs/KIEM_THU.md` giai đoạn 2.
