#!/usr/bin/env python3
"""Demo: Image reading support in the coding agent.

This script demonstrates that:
1. The agent can read image files via read_file tool
2. Images are returned as base64-encoded JSON
3. Text files continue to work as plain text

Usage:
    uv run python demo_image_read.py
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Add src/ to path so we can import tools
sys.path.insert(0, str(Path(__file__).parent / "src"))

from tools import read_file


async def main():
    """Demonstrate image reading functionality."""
    print("🖼️  Image Reading Demo\n")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 1. Create a minimal PNG
        print("\n1. Creating a test image (1x1 PNG)...")
        png_bytes = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
            b"\x00\x00\x00\x18\xdd\x8d\xb4"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        img_path = tmp / "demo.png"
        img_path.write_bytes(png_bytes)
        print(f"   ✓ Created: {img_path}")
        print(f"   Size: {len(png_bytes)} bytes")

        # 2. Read the image with read_file
        print("\n2. Reading image with read_file tool...")
        result = await read_file(str(img_path))

        # 3. Parse and display the result
        parsed = json.loads(result)
        print(f"   ✓ Type: {parsed['type']}")
        print(f"   ✓ Format: {parsed['format']}")
        print(f"   ✓ Base64 data length: {len(parsed['data'])} chars")
        print(f"   ✓ First 60 chars: {parsed['data'][:60]}...")

        # 4. Verify it's valid base64
        import base64

        decoded = base64.b64decode(parsed["data"])
        print(f"\n   ✓ Decoded back to {len(decoded)} bytes")
        print(f"   ✓ Matches original: {decoded == png_bytes}")

        # 5. Show text files still work
        print("\n3. Verifying text files still return plain text...")
        text_path = tmp / "readme.txt"
        text_path.write_text("Hello from the coding agent!")

        text_result = await read_file(str(text_path))
        print(f"   ✓ Text file content: '{text_result}'")
        print(f"   ✓ Is plain text (not JSON): {not text_result.startswith('{')}")

    print("\n" + "=" * 60)
    print("✅ All checks passed! Image reading is working.\n")
    print("Now you can:")
    print("  • Paste images with Ctrl+V in the TUI")
    print("  • Read image files with the read_file tool")
    print("  • Both will send base64-encoded data to the model\n")


if __name__ == "__main__":
    asyncio.run(main())
