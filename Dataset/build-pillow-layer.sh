#!/bin/bash
# ============================================================
# 🧱 build-pillow-layer.sh
# Build Pillow (PIL) layer for AWS Lambda (Python 3.9 / x86_64)
# ============================================================

set -e

echo "🧹 Cleaning old build..."
rm -rf python pillow-layer.zip

echo "📁 Creating directory structure..."
mkdir -p python

echo "⬆️ Upgrading pip..."
pip install --upgrade pip

echo "📦 Installing Pillow==10.4.0 to ./python ..."
pip install "pillow==10.4.0" -t python

echo "🗜️ Zipping layer..."
zip -r pillow-layer.zip python > /dev/null

echo ""
echo "✅ Done! Layer package created: pillow-layer.zip"
echo "   ➤ Upload this ZIP in Lambda > Layers > Create layer"
echo "   ➤ Compatible runtime: Python 3.9"
echo "   ➤ Architecture: x86_64"
