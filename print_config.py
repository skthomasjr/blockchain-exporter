#!/usr/bin/env python3
"""Print resolved blockchain-exporter configuration."""

import sys
from pathlib import Path

# Add src to Python path
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

# Import and run - pass through command line arguments with --print-resolved
from blockchain_exporter.cli import main  # noqa: E402

if __name__ == "__main__":
    # Skip script name, add --print-resolved, then pass remaining args
    args = ["--print-resolved"] + sys.argv[1:]
    sys.exit(main(args))
