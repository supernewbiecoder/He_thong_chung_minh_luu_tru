# provider — nút lưu trữ

Chạy độc lập. Người bán dung lượng chỉ cần tải thư mục này.

## Endpoint  [SPEC §C.2.1]

    POST /v1/quote                    I-01  khách hỏi giá
    POST /v1/deals/{id}/chunks        I-01  khách gửi dữ liệu (streaming)
    GET  /v1/deals/{id}/status
    GET  /v1/health

## Ra ngoài

    RPC Celestia   I-04  PayForBlobs, share v1 có trường signer
    RPC EVM        I-03  registerSealed / activate / claimSettlement

## Không làm gì

Nút **không bao giờ** gửi bundle lên EVM. Bundle đi lên Celestia. Cả đời một hợp
đồng nút chỉ gửi EVM ba giao dịch: registerSealed, activate, claimSettlement.
Nếu 10.000 nút mỗi ngày gửi một giao dịch EVM thì đó là đường cơ sở mà kiến trúc
này bác bỏ — nó chết ở 727 nút. [SPEC §I.1.1]
