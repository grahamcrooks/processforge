"""
Quick smoke-test for Stage 3 — Claude API integration.
Creates a minimal PNG in-memory and sends it to Claude.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python test_claude.py [path/to/diagram.png]
"""
import asyncio
import json
import sys
import struct
import zlib


def _make_test_png() -> bytes:
    """Create a minimal 1x1 white PNG entirely in-memory (no Pillow needed)."""
    def chunk(name: bytes, data: bytes) -> bytes:
        c = name + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00\xFF\xFF\xFF"          # filter byte + RGB white
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


async def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, "rb") as f:
            image_bytes = f.read()
        filename = path.split("/")[-1]
        print(f"Using diagram: {path}")
    else:
        image_bytes = _make_test_png()
        filename = "test_diagram.png"
        print("No PNG provided — using minimal 1x1 test PNG.")
        print("Tip: python test_claude.py path/to/your/diagram.png\n")

    # Import here so config loads from .env
    from services.claude_service import analyse_diagrams

    print(f"Sending {filename} to Claude ({len(image_bytes):,} bytes)...")
    process_data, warnings = await analyse_diagrams([(filename, image_bytes)])

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ! {w}")

    print("\nProcess data returned:")
    print(json.dumps(process_data, indent=2))
    print(f"\nSteps: {len(process_data.get('steps', []))}")
    print(f"Lanes: {process_data.get('lanes', [])}")
    print(f"Data entities: {process_data.get('data_entities', [])}")
    print(f"Integrations: {process_data.get('integrations', [])}")


if __name__ == "__main__":
    asyncio.run(main())
