"""Minimal, dependency-free writer for monospaced text PDFs.

A DARS export is a printout of a fixed-width terminal report, so a fixture only
needs Courier and hard line breaks.  Writing the ~40 lines of PDF syntax here
keeps the synthetic fixtures reproducible from source on any machine, which
matters because ``.gitignore`` excludes ``*.pdf`` and the generated files are
therefore never committed.
"""

from __future__ import annotations

from pathlib import Path

LINES_PER_PAGE = 66
FONT_SIZE = 8.0
LEADING = 10.0
LEFT_MARGIN = 36.0
TOP = 756.0
PAGE = (612.0, 792.0)


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    body = [f"BT /F1 {FONT_SIZE} Tf {LEADING} TL {LEFT_MARGIN} {TOP} Td"]
    for line in lines:
        # Latin-1 is what the PDF base-14 Courier encoding accepts directly.
        safe = _escape(line).encode("latin-1", "replace").decode("latin-1")
        body.append(f"({safe}) Tj T*")
    body.append("ET")
    return "\n".join(body).encode("latin-1")


def write_text_pdf(path: str | Path, text: str) -> Path:
    """Render ``text`` to a text-extractable PDF at ``path``.

    Form feeds start a new page, matching how DARS paginates; otherwise pages
    break every ``LINES_PER_PAGE`` lines.
    """
    pages: list[list[str]] = []
    for chunk in text.split("\f"):
        lines = chunk.splitlines()
        if not lines:
            continue
        for start in range(0, len(lines), LINES_PER_PAGE):
            pages.append(lines[start : start + LINES_PER_PAGE])
    if not pages:
        pages = [[""]]

    objects: list[bytes] = []

    def add(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
               b"/Encoding /WinAnsiEncoding >>")
    # The pages object needs its children's numbers, so reserve its slot first.
    pages_id = add(b"")
    page_ids: list[int] = []
    for lines in pages:
        stream = _content_stream(lines)
        content = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox "
                f"[0 0 {PAGE[0]:g} {PAGE[1]:g}] /Resources << /Font << /F1 {font} 0 R >> >> "
                f"/Contents {content} 0 R >>".encode()
            )
        )
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode()
    )
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + payload + b"\nendobj\n"
    start_xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
        f"startxref\n{start_xref}\n%%EOF\n".encode()
    )

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(bytes(out))
    return destination
