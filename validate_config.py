#!/usr/bin/env python3
"""Validate blockchain-exporter configuration."""

import sys
from pathlib import Path

# Add src to Python path
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

# Import and run - pass through command line arguments
from blockchain_exporter.cli import main  # noqa: E402

if __name__ == "__main__":
    # Skip script name, pass remaining args
    sys.exit(main(sys.argv[1:]))
