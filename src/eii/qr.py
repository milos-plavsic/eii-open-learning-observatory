"""Small dependency-free QR encoder for LAN onboarding URLs (versions 1-4, level L)."""

from __future__ import annotations

from html import escape

_CAPACITY = {1: (19, 7), 2: (34, 10), 3: (55, 15), 4: (80, 20)}


def qr_matrix(text: str) -> list[list[bool]]:
    raw = text.encode("utf-8")
    version = next((v for v, (data, _) in _CAPACITY.items() if len(raw) <= data - 2), None)
    if version is None:
        raise ValueError("onboarding QR text must fit version 1-4 (approximately 78 ASCII bytes)")
    data_count, ecc_count = _CAPACITY[version]
    bits = [0, 1, 0, 0, *_bits(len(raw), 8)]
    for byte in raw:
        bits.extend(_bits(byte, 8))
    bits.extend([0] * min(4, data_count * 8 - len(bits)))
    bits.extend([0] * ((-len(bits)) % 8))
    data = [sum(bits[i + j] << (7 - j) for j in range(8)) for i in range(0, len(bits), 8)]
    pads = (0xEC, 0x11)
    while len(data) < data_count:
        data.append(pads[(len(data) - ((len(bits) + 7) // 8)) % 2])
    codewords = data + _reed_solomon(data, ecc_count)

    size = version * 4 + 17
    modules = [[False] * size for _ in range(size)]
    function = [[False] * size for _ in range(size)]

    def set_module(x: int, y: int, value: bool) -> None:
        if 0 <= x < size and 0 <= y < size:
            modules[y][x] = value
            function[y][x] = True

    def finder(cx: int, cy: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                distance = max(abs(dx), abs(dy))
                set_module(cx + dx, cy + dy, distance != 2 and distance != 4)

    finder(3, 3)
    finder(size - 4, 3)
    finder(3, size - 4)
    for i in range(8, size - 8):
        set_module(6, i, i % 2 == 0)
        set_module(i, 6, i % 2 == 0)
    if version > 1:
        center = size - 7
        for cy, cx in ((6, center), (center, 6), (center, center)):
            if function[cy][cx]:
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    set_module(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    # Reserve and then draw format information for error correction L, mask 0.
    format_positions_a = (
        [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14 - i, 8) for i in range(9, 15)]
    )
    format_positions_b = [(size - 1 - i, 8) for i in range(8)] + [
        (8, size - 15 + i) for i in range(8, 15)
    ]
    format_data = 0b01 << 3
    remainder = format_data << 10
    generator = 0x537
    for bit in range(14, 9, -1):
        if (remainder >> bit) & 1:
            remainder ^= generator << (bit - 10)
    format_bits = ((format_data << 10) | remainder) ^ 0x5412
    for i, (x, y) in enumerate(format_positions_a):
        set_module(x, y, bool((format_bits >> i) & 1))
    for i, (x, y) in enumerate(format_positions_b):
        set_module(x, y, bool((format_bits >> i) & 1))
    set_module(8, size - 8, True)

    stream = [bit for byte in codewords for bit in _bits(byte, 8)]
    index = 0
    upward = True
    right = size - 1
    while right >= 1:
        if right == 6:
            right -= 1
        for vertical in range(size):
            y = size - 1 - vertical if upward else vertical
            for x in (right, right - 1):
                if not function[y][x]:
                    bit = stream[index] if index < len(stream) else 0
                    modules[y][x] = bool(bit) ^ ((x + y) % 2 == 0)
                    index += 1
        upward = not upward
        right -= 2
    return modules


def qr_svg(text: str, *, scale: int = 8, border: int = 4) -> str:
    matrix = qr_matrix(text)
    size = len(matrix) + border * 2
    path = "".join(
        f"M{x + border},{y + border}h1v1h-1z"
        for y, row in enumerate(matrix)
        for x, value in enumerate(row)
        if value
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size * scale}" height="{size * scale}" role="img" '
        f'aria-label="QR code for {escape(text)}"><rect width="100%" height="100%" fill="white"/>'
        f'<path d="{path}" fill="black"/></svg>'
    )


def _bits(value: int, width: int) -> list[int]:
    return [(value >> i) & 1 for i in range(width - 1, -1, -1)]


def _multiply(x: int, y: int) -> int:
    result = 0
    for _ in range(8):
        result ^= x if y & 1 else 0
        y >>= 1
        x = (x << 1) ^ (0x11D if x & 0x80 else 0)
    return result


def _reed_solomon(data: list[int], degree: int) -> list[int]:
    generator = [1]
    root = 1
    for _ in range(degree):
        next_generator = [0] * (len(generator) + 1)
        for i, coefficient in enumerate(generator):
            next_generator[i] ^= coefficient
            next_generator[i + 1] ^= _multiply(coefficient, root)
        generator = next_generator
        root = _multiply(root, 2)
    remainder = [0] * degree
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = [*remainder[1:], 0]
        for i in range(degree):
            remainder[i] ^= _multiply(generator[i + 1], factor)
    return remainder
