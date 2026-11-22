"""Bitmap OCR for synthetic scanned pages. No external engine."""

from __future__ import annotations

import random

# 5x7 glyphs. A spacer column separates them inside a page image.
_FONT: dict[str, tuple[str, ...]] = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10001", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
}
_WIDTH = 5
_HEIGHT = 7


def render(text: str) -> list[str]:
    rows = [""] * _HEIGHT
    for character in text:
        glyph = _FONT[character]
        for index, row in enumerate(glyph):
            rows[index] += row + "0"
    return rows


def degrade(rows: list[str], level: str, seed: int) -> list[str]:
    rng = random.Random(seed)
    copied = [list(row) for row in rows]
    if level == "skew":
        copied = [list(row[-1] + row[:-1]) for row in rows]
    elif level == "noise":
        for row in copied:
            for index, bit in enumerate(row):
                if rng.random() < 0.02:
                    row[index] = "0" if bit == "1" else "1"
    elif level == "low_resolution":
        for row in copied[::2]:
            for index in range(len(row)):
                row[index] = "0"
    else:
        raise ValueError(level)
    return ["".join(row) for row in copied]


def recognize(rows: list[str]) -> tuple[str, float]:
    if not rows or not rows[0]:
        return "", 0.0
    width = len(rows[0])
    glyphs: list[str] = []
    matched = 0
    column = 0
    while column + _WIDTH <= width:
        block = tuple(row[column : column + _WIDTH] for row in rows)
        character, distance = _nearest(block)
        glyphs.append(character)
        matched += int(distance == 0)
        column += _WIDTH + 1
    text = "".join(glyphs).rstrip()
    confidence = 0.0 if not glyphs else matched / len(glyphs)
    return text, confidence


def pdf_with_bitmap(rows: list[str]) -> bytes:
    height = len(rows)
    width = len(rows[0])
    samples = bytearray()
    for row in rows:
        for bit in row:
            samples.append(255 if bit == "1" else 0)
    image = (
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length {len(samples)} >>\n"
        f"stream\n".encode()
        + bytes(samples)
        + b"\nendstream"
    )
    content = f"q {width} 0 0 {height} 0 0 cm /Im Do Q".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] "
        b"/Resources << /XObject << /Im 4 0 R >> >> /Contents 5 0 R >>",
        image,
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{number} 0 obj\n".encode())
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(body)


def read_pdf(pdf: bytes) -> tuple[str, float]:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf))
    images = list(reader.pages[0].images)
    if not images:
        return "", 0.0
    image = images[0].image
    if image is None:
        return "", 0.0
    pixels = list(image.get_flattened_data())
    rows: list[str] = []
    for y_index in range(image.height):
        start = y_index * image.width
        rows.append("".join("1" if pixel else "0" for pixel in pixels[start : start + image.width]))
    return recognize(rows)


def _nearest(block: tuple[str, ...]) -> tuple[str, int]:
    if all(bit == "0" for row in block for bit in row):
        return " ", 0
    best = "?"
    distance = _WIDTH * _HEIGHT
    for character, glyph in _FONT.items():
        if character == " ":
            continue
        score = sum(left != right for left, right in zip(block, glyph, strict=True))
        if score < distance:
            best = character
            distance = score
    return best, distance
