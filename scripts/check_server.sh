#!/usr/bin/env bash
# Pings le serveur pour découvrir : OS, GPU, RAM, Python.
# Usage : ssh user@server "bash -s" < scripts/check_server.sh

echo "=== OS ==="
uname -a
echo
echo "=== Distribution ==="
cat /etc/os-release 2>/dev/null | head -3
echo
echo "=== CPU ==="
lscpu | grep -E "Model name|CPU\(s\):" | head -3
echo
echo "=== RAM ==="
free -h | head -2
echo
echo "=== GPU NVIDIA ==="
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null \
        || echo "nvidia-smi installé mais ne répond pas"
else
    echo "Pas de nvidia-smi (pas de GPU NVIDIA, ou drivers non installés)"
    # Check sans drivers
    if lspci 2>/dev/null | grep -i nvidia >/dev/null; then
        echo "MAIS lspci voit une carte NVIDIA :"
        lspci | grep -i nvidia
    fi
fi
echo
echo "=== Python ==="
which python3 python 2>/dev/null
python3 --version 2>/dev/null
echo
echo "=== Disque ==="
df -h $HOME | head -2
