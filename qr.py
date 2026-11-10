#!/usr/bin/env python3
"""A small QR code encoder (byte mode, error correction level M, versions 1-10: up to 213
bytes), stdlib only. Used for the "scan to open on your phone" code on the page.

  qr.matrix("http://192.168.1.20:8765") -> list of rows of 0/1 (1 = dark), no quiet zone
  qr.svg(text)                          -> an SVG string with a 4-module quiet zone
"""

# (data codewords per block groups, EC codewords per block) for level M
_M = {1: ([(1, 16)], 10), 2: ([(1, 28)], 16), 3: ([(1, 44)], 26), 4: ([(2, 32)], 18), 5: ([(2, 43)], 24),
      6: ([(4, 27)], 16), 7: ([(4, 31)], 18), 8: ([(2, 38), (2, 39)], 22), 9: ([(3, 36), (2, 37)], 22),
      10: ([(4, 43), (1, 44)], 26)}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38],
          8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}

# GF(256) with the QR polynomial x^8+x^4+x^3+x^2+1
_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x; _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_ec(data, n):
    """Reed-Solomon error-correction codewords (n of them) for data."""
    gen = [1]
    for i in range(n):                                   # prod (x - a^i)
        nxt = [0] * (len(gen) + 1)
        for j, c in enumerate(gen):
            nxt[j] ^= c
            nxt[j + 1] ^= _gmul(c, _EXP[i])
        gen = nxt
    rem = list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gmul(gen[j], c)
    return rem[len(data):]


def _bch(value, poly, bits):
    v = value << bits
    top = poly.bit_length() - 1
    while v.bit_length() - 1 >= top:
        v ^= poly << (v.bit_length() - 1 - top)
    return (value << bits) | v


def _codewords(data):
    for ver in range(1, 11):
        groups, ecn = _M[ver]
        cap = sum(b * d for b, d in groups)
        ccbits = 8 if ver < 10 else 16
        if 4 + ccbits + 8 * len(data) <= cap * 8:
            break
    else:
        raise ValueError("text too long for a QR code here (max 213 bytes)")
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in range(ccbits - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, cap * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    cw = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(cw) < cap:
        cw.append(pad[(len(cw) - len(bits) // 8) % 2])
    blocks, k = [], 0
    for b, d in groups:
        for _ in range(b):
            blocks.append(cw[k:k + d]); k += d
    ecs = [_rs_ec(bl, ecn) for bl in blocks]
    out = []
    for i in range(max(len(bl) for bl in blocks)):
        out += [bl[i] for bl in blocks if i < len(bl)]
    for i in range(ecn):
        out += [e[i] for e in ecs]
    return ver, out


_MASKS = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
          lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
          lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
          lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]


def _base(ver):
    n = 17 + 4 * ver
    m = [[0] * n for _ in range(n)]
    fn = [[False] * n for _ in range(n)]                 # function modules (not data)

    def put(r, c, v):
        m[r][c] = v; fn[r][c] = True

    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):      # finders + separators
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = r0 + r, c0 + c
                if 0 <= rr < n and 0 <= cc < n:
                    put(rr, cc, 1 if (0 <= r <= 6 and 0 <= c <= 6 and
                                      (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))) else 0)
    for i in range(8, n - 8):                            # timing
        put(6, i, (i + 1) % 2); put(i, 6, (i + 1) % 2)
    al = _ALIGN[ver]
    for r in al:
        for c in al:
            if (r, c) in ((al[0], al[0]), (al[0], al[-1]), (al[-1], al[0])):   # under the finders
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    put(r + dr, c + dc, 1 if max(abs(dr), abs(dc)) != 1 else 0)
    for i in range(9):                                   # reserve format areas
        if not fn[8][i]: put(8, i, 0)
        if not fn[i][8]: put(i, 8, 0)
    for i in range(8):
        put(8, n - 1 - i, 0); put(n - 1 - i, 8, 0)
    put(n - 8, 8, 1)                                     # the dark module
    if ver >= 7:
        v = _bch(ver, 0x1F25, 12)
        for i in range(18):
            bit = (v >> i) & 1
            put(n - 11 + i % 3, i // 3, bit); put(i // 3, n - 11 + i % 3, bit)
    return m, fn


def _place(m, fn, cw):
    n = len(m)
    bits = [(b >> i) & 1 for b in cw for i in range(7, -1, -1)]
    k, up, c = 0, True, n - 1
    while c > 0:
        if c == 6:
            c -= 1
        for i in range(n):
            r = n - 1 - i if up else i
            for cc in (c, c - 1):
                if not fn[r][cc]:
                    m[r][cc] = bits[k] if k < len(bits) else 0
                    k += 1
        up = not up
        c -= 2


def _format(m, mask):
    n = len(m)
    v = _bch((0b00 << 3) | mask, 0x537, 10) ^ 0x5412     # level M = 00
    bits = [(v >> i) & 1 for i in range(15)]             # bit 0 = least significant
    for i in range(15):
        b = bits[i]
        # around the top-left finder
        if i < 6:
            m[i][8] = b
        elif i < 8:
            m[i + 1][8] = b
        elif i == 8:
            m[8][7] = b
        else:
            m[8][14 - i] = b
        # the copy split between the other two finders
        if i < 8:
            m[8][n - 1 - i] = b
        else:
            m[n - 15 + i][8] = b
    m[n - 8][8] = 1


def _penalty(m):
    n = len(m); p = 0
    for grid in (m, [list(col) for col in zip(*m)]):
        for row in grid:
            run, prev = 0, None
            for v in row:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        p += run - 2
                    run, prev = 1, v
            if run >= 5:
                p += run - 2
            s = "".join(map(str, row))
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                p += 3
    dark = sum(map(sum, m))
    p += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
    return p


def matrix(text):
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    ver, cw = _codewords(data)
    best = None
    for mask in range(8):
        m, fn = _base(ver)
        _place(m, fn, cw)
        f = _MASKS[mask]
        for r in range(len(m)):
            for c in range(len(m)):
                if not fn[r][c] and f(r, c):
                    m[r][c] ^= 1
        _format(m, mask)
        score = _penalty(m)
        if best is None or score < best[0]:
            best = (score, m)
    return best[1]


def svg(text, module=8, fg="#000", bg="#fff"):
    m = matrix(text)
    n = len(m) + 8
    path = "".join(f"M{c + 4},{r + 4}h1v1h-1z" for r, row in enumerate(m) for c, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{n * module}" height="{n * module}" '
            f'shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="{bg}"/><path d="{path}" fill="{fg}"/></svg>')
