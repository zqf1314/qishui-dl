#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spade_a -> 内容密钥（32 hex 字符）"""
import base64

def popcount(x):
    return bin(x).count("1")

def spade_key(spade_a: str) -> str:
    data = base64.b64decode(spade_a + "=" * (-len(spade_a) % 4))
    seed = data[0] ^ data[1] ^ data[2]
    buflen = (len(data) - seed + 0x2F) & 0xFFFFFFFF
    raw = data[1:1 + buflen]
    pe, po = 0xFA, 0x55
    B = bytearray()
    for i in range(buflen):
        x = raw[i] ^ (pe if i % 2 == 0 else po)
        d = -(21 + popcount(i))
        B.append((x + d) & 0xFF)
        if i % 2 == 0:
            pe = raw[i]
        else:
            po = raw[i]
    c = chr(B[0])
    dig = int(c, 16)
    key = bytes(B[1:buflen - dig])
    return key.decode("ascii", "replace")

if __name__ == "__main__":
    import sys
    print(spade_key(sys.argv[1]))
