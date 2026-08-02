"""ThinkDome Initramfs Generator.

Bundles init script and busybox binary into initramfs.cpio.gz for MicroVM boot.
"""

import gzip
import io
from pathlib import Path

INITRAMFS_DIR = Path(__file__).resolve().parent
INIT_SCRIPT = INITRAMFS_DIR / "init.sh"
OUTPUT_CPIO = INITRAMFS_DIR / "initramfs.cpio.gz"


def create_initramfs_bundle(output_path: Path = OUTPUT_CPIO) -> Path:
    """Build a lightweight CPIO initramfs archive containing init.sh."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    init_content = INIT_SCRIPT.read_bytes() if INIT_SCRIPT.exists() else b"#!/bin/sh\necho ThinkDome Init\nexec /sbin/init\n"

    # Minimal CPIO header generator for standard newc format
    # Magic: "070701"
    def make_cpio_entry(filename: str, content: bytes, mode: int = 0o755) -> bytes:
        filename_bytes = filename.encode("utf-8") + b"\x00"
        header = f"070701{0:08x}{mode:08x}{0:08x}{0:08x}{1:08x}{0:08x}{len(content):08x}{0:08x}{0:08x}{0:08x}{0:08x}{len(filename_bytes):08x}{0:08x}".encode("ascii")
        # Pad header + filename to 4-byte boundary
        pad1 = b"\x00" * ((4 - (len(header) + len(filename_bytes)) % 4) % 4)
        pad2 = b"\x00" * ((4 - len(content) % 4) % 4)
        return header + filename_bytes + pad1 + content + pad2

    out = io.BytesIO()
    out.write(make_cpio_entry("init", init_content, mode=0o755))
    out.write(make_cpio_entry("TRAILER!!!", b"", mode=0))

    compressed = gzip.compress(out.getvalue())
    output_path.write_bytes(compressed)
    return output_path


if __name__ == "__main__":
    path = create_initramfs_bundle()
    print(f"Generated initramfs at: {path} ({len(path.read_bytes())} bytes)")
