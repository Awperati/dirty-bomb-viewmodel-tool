"""Generates assets/icon.ico (crosshair ring on a dark tile). Standard library only."""
import os, struct, zlib

ORANGE, TILE = (255, 122, 26), (22, 26, 33)

def pixel(u, v):
    """RGBA at normalised coords u,v in [-1,1]."""
    qx, qy = abs(u) - 0.72, abs(v) - 0.72
    sdf = (max(qx, 0) ** 2 + max(qy, 0) ** 2) ** 0.5 + min(max(qx, qy), 0) - 0.22   # rounded tile
    if sdf > 0:
        return (0, 0, 0, 0)
    r = (u * u + v * v) ** 0.5
    hit = abs(r - 0.52) < 0.09 or r < 0.1 or (0.2 < abs(u) < 0.95 and abs(v) < 0.06 and r > 0.36) \
        or (0.2 < abs(v) < 0.95 and abs(u) < 0.06 and r > 0.36)
    return (*(ORANGE if hit else TILE), 255)

def render(n, ss=3):
    rows = []
    for y in range(n):
        row = []
        for x in range(n):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    r, g, b, a = pixel(2 * (x + (sx + .5) / ss) / n - 1, 2 * (y + (sy + .5) / ss) / n - 1)
                    acc[0] += r * a; acc[1] += g * a; acc[2] += b * a; acc[3] += a
            k = ss * ss
            a = acc[3]
            row.append((acc[0] // a, acc[1] // a, acc[2] // a, a // k) if a else (0, 0, 0, 0))
        rows.append(row)
    return rows

def bmp(n):
    px = render(n)
    body = b"".join(struct.pack("<4B", b, g, r, a) for row in reversed(px) for r, g, b, a in row)
    mask = bytes(((n + 31) // 32 * 4) * n)
    return struct.pack("<IiiHHIIiiII", 40, n, n * 2, 1, 32, 0, len(body) + len(mask), 0, 0, 0, 0) + body + mask

def png(n):
    px = render(n)
    raw = b"".join(b"\x00" + b"".join(struct.pack("4B", *p) for p in row) for row in px)
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")

def main():
    sizes = [16, 24, 32, 48, 64, 256]
    imgs = [png(n) if n == 256 else bmp(n) for n in sizes]
    head = struct.pack("<HHH", 0, 1, len(sizes))
    off, entries = 6 + 16 * len(sizes), b""
    for n, d in zip(sizes, imgs):
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(d), off)
        off += len(d)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(head + entries + b"".join(imgs))
    print("wrote", out)

if __name__ == "__main__":
    main()
