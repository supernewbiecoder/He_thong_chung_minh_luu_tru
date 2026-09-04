#!/usr/bin/env python3
"""Kiểm tĩnh mã Solidity — bắt hai lỗi mà `solc` chỉ báo rất muộn hoặc rất mơ hồ.

① CHUỖI ngoài ASCII

Solidity từ chối ký tự ngoài ASCII trong chuỗi thường — phải viết unicode"...".
Một ký tự lọt vào là cả bản dựng chết với "Error (8936): Invalid character in
string", và thông điệp đó không nói rõ phải sửa thế nào.

Comment thì thoải mái tiếng Việt. Chỉ CHUỖI mới bị ràng buộc.

② STRUCT quá 16 trường trong `mapping public`

Solidity TỰ SINH getter cho mapping public, trả về từng trường rời. Struct quá
16 trường thì getter vượt giới hạn stack EVM và báo "Stack too deep" — một lỗi
KHÔNG chỉ vào dòng nào, vì hàm gây ra nó không do người viết.

Dấu hiệu nhận biết: rỗng hoá TẤT CẢ thân hàm mà vẫn tràn.

Cách chữa: đổi mapping sang `internal` và viết getter trả `StructName memory`.

    python3 chain/check_ascii.py
"""
import glob
import io
import re
import sys


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


MAX_GETTER_FIELDS = 16
"""EVM truy cập được 16 khe stack. Getter trả nhiều hơn thế là tràn."""


def struct_fields(src: str) -> dict[str, int]:
    out = {}
    for m in re.finditer(r"struct\s+(\w+)\s*\{(.*?)\n\s*\}", src, re.S):
        body = re.sub(r"///[^\n]*|//[^\n]*", "", m.group(2))
        out[m.group(1)] = len([l for l in body.split("\n") if l.strip().endswith(";")])
    return out


def check_public_mappings(src: str, path: str) -> list[str]:
    problems = []
    sizes = struct_fields(src)
    for m in re.finditer(r"mapping\s*\([^)]*=>\s*(\w+)\s*\)\s+public\s+(\w+)", src):
        struct, name = m.group(1), m.group(2)
        n = sizes.get(struct)
        if n and n > MAX_GETTER_FIELDS:
            problems.append(
                f"  {path}: `mapping public {name}` trả về {struct} có {n} trường "
                f"(> {MAX_GETTER_FIELDS}).\n"
                f"      Getter tự sinh sẽ gây 'Stack too deep' KHÔNG kèm số dòng.\n"
                f"      Sửa: đổi sang `internal _{name}` + getter trả `{struct} memory`."
            )
    return problems


def main() -> int:
    bad = []
    stack = []
    for f in sorted(glob.glob("chain/**/*.sol", recursive=True)):
        if "/lib/" in f:
            continue
        raw = io.open(f, encoding="utf-8").read()
        stack += check_public_mappings(raw, f)
        code = strip_comments(raw)
        for n, line in enumerate(code.split("\n"), 1):
            for m in re.finditer(r'(?<!unicode)"([^"]*)"', line):
                offenders = sorted({c for c in m.group(1) if ord(c) > 127})
                if offenders:
                    bad.append((f, n, offenders, m.group(1)[:60]))
    for f, n, cs, txt in bad:
        print(f"  {f}:{n}  ký tự {cs} trong chuỗi: {txt!r}")
    if bad:
        print(f"\n  {len(bad)} chuỗi có ký tự ngoài ASCII — Solidity sẽ từ chối biên dịch.")
        print('  Sửa: bỏ ký tự, hoặc dùng unicode"..." nếu thật sự cần.')
    for p in stack:
        print(p)
    if bad or stack:
        return 1
    print("  Chuỗi đều ASCII · không mapping public nào vượt giới hạn stack.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
