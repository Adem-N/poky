#!/usr/bin/env bash
# Déploiement Poky sur un serveur Linux + lancement training NFSP.
#
# Usage local depuis Windows :
#   ssh user@server "bash -s" < scripts/deploy_train.sh
#
# Ou depuis le serveur après git clone :
#   bash scripts/deploy_train.sh
#
# Le script :
#   1. Détecte si un GPU NVIDIA est dispo
#   2. Installe les dépendances dans un venv local
#   3. Lance le training NFSP (500k épisodes par défaut)
#   4. Sauvegarde les checkpoints dans data/nfsp_3max_server/
#
# Pour récupérer les modèles entraînés ensuite :
#   scp -r user@server:~/Poky/data/nfsp_3max_server/ ./data/

set -e

REPO_DIR="${REPO_DIR:-$HOME/Poky}"
EPISODES="${EPISODES:-500000}"
SAVE_DIR="${SAVE_DIR:-data/nfsp_3max_server}"

echo "=== Poky training deploy ==="
echo "Repo  : $REPO_DIR"
echo "Episodes : $EPISODES"
echo

# 1. Clone si pas déjà fait
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "→ Cloning repo (REPO_URL must be set, e.g. https://github.com/<you>/Poky.git)"
    if [ -z "$REPO_URL" ]; then
        echo "ERROR: REPO_URL not set. Export it first: export REPO_URL=https://..."
        exit 1
    fi
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# 2. GPU detection
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    echo "→ NVIDIA GPU détecté :"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
    DEVICE="cuda"
else
    echo "→ Pas de GPU NVIDIA détecté, training sur CPU"
    DEVICE="cpu"
fi

# 3. Venv + deps
if [ ! -d ".venv" ]; then
    echo "→ Création du venv (Python 3)"
    python3 -m venv .venv
fi
source .venv/bin/activate
echo "→ Install requirements"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# 4. Pour GPU : install PyTorch CUDA si pas déjà
if [ "$DEVICE" = "cuda" ]; then
    if ! python -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
        echo "→ Réinstall PyTorch avec support CUDA"
        pip install --quiet --upgrade torch --index-url https://download.pytorch.org/whl/cu121
    fi
fi

# 5. Lancement training (rl_lr=0.0005 corrigé)
echo
echo "=== Démarrage training NFSP ($EPISODES épisodes, device=$DEVICE) ==="
python -m poky.training.nfsp_train \
    --episodes "$EPISODES" \
    --save-every $((EPISODES / 20)) \
    --eval-every $((EPISODES / 50)) \
    --rl-lr 0.0005 \
    --device "$DEVICE" \
    --save-dir "$SAVE_DIR"

echo
echo "=== Terminé. Récupère les modèles avec :"
echo "  scp -r user@server:$REPO_DIR/$SAVE_DIR/ ./data/"
