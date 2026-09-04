#!/usr/bin/env python3
"""Kiểm mọi CHUỖI trong Solidity chỉ dùng ASCII.

Solidity từ chối ký tự ngoài ASCII trong chuỗi thường — phải viết unicode"...".
Một ký tự lọt vào là cả bản dựng chết với "Error (8936): Invalid character in
string", và thông điệp đó không nói rõ phải sửa thế nào.

Comment thì thoải mái tiếng Việt. Chỉ CHUỖI mới bị ràng buộc.

    python3 chain/check_ascii.py
"""
import glob
import io
import re
import sys


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def main() -> int:
    bad = []
    for f in sorted(glob.glob("chain/**/*.sol", recursive=True)):
        if "/lib/" in f:
            continue
        code = strip_comments(io.open(f, encoding="utf-8").read())
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
        return 1
    print("  Mọi chuỗi Solidity đều là ASCII.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
