#!/usr/bin/env python3
"""Development entry point for blockchain-exporter."""

import sys
from pathlib import Path

# Add src to Python path
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

# Import and run
from blockchain_exporter.main import run  # noqa: E402

if __name__ == "__main__":
    run()
