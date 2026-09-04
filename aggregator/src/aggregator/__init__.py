"""
═══════════════════════════════════════════════════════════════════════════════
 aggregator — GỘP VÀ NỘP LÊN EVM
 [SPEC §A.2 vai trò 4] · [SPEC UC-06] · [SPEC §F.2.3]
═══════════════════════════════════════════════════════════════════════════════

 Gom D×S_ns ChildProof của cả epoch, gộp theo cây đệ quy trong SP1, bọc Groth16
 MỘT LẦN, rồi nộp 844 byte lên EVM.

 ── CHỖ O(N) BIẾN THÀNH O(1) ─────────────────────────────────────────────

   10.000 bằng chứng Spartan   137,8 MB  trên Celestia
   768 ChildProof                        gộp đệ quy
   1 Groth16 + public values      844 B  lên EVM

 Tỉ lệ nén ~163.000 lần. Và 487.109 gas KHÔNG ĐỔI dù mạng có 10 hay 10.000
 hợp đồng.
"""
