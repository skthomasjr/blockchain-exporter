#!/bin/bash
# Run blockchain-exporter
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd)/src"
PYTHON=$(pipx run poetry env info --path)/bin/python
exec "$PYTHON" -m blockchain_exporter.main "$@"

