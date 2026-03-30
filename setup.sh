#!/usr/bin/env bash
# setup.sh — First-time setup for the 3D Floor Plan Pipeline Backend
# Run once: bash setup.sh
# Then start the server: node server.js

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  3D Floor Plan Pipeline — Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check Node.js
if ! command -v node &>/dev/null; then
  echo "❌  Node.js not found. Install from https://nodejs.org (v16+)"
  exit 1
fi
echo "✅  Node.js $(node --version)"

# Check Python 3
if ! command -v python3 &>/dev/null; then
  echo "❌  Python 3 not found. Install from https://python.org (3.8+)"
  exit 1
fi
echo "✅  Python $(python3 --version)"

# Install Python dependencies
echo ""
echo "Installing Python dependencies (opencv-python-headless, numpy)…"
pip3 install opencv-python-headless numpy --quiet

echo ""
echo "✅  Python dependencies installed"

# Create uploads dir
mkdir -p uploads
echo "✅  uploads/ directory ready"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete!  Start the server with:"
echo "    node server.js"
echo ""
echo "  Then open Index.html in your browser."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
