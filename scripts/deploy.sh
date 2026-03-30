#!/bin/bash
# ============================================
# Deploy script para DigitalOcean
# Uso: ./scripts/deploy.sh [test|paper|live]
# ============================================

set -e

MODE=${1:-TEST}
REMOTE_USER="root"
REMOTE_HOST="YOUR_DROPLET_IP"  # ← Cambiar
REMOTE_DIR="/opt/scalping-bot"
REPO_URL="YOUR_GITHUB_REPO"    # ← Cambiar

echo "═══════════════════════════════════"
echo "  DEPLOYING SCALPING BOT"
echo "  Mode: $MODE"
echo "═══════════════════════════════════"

# 1. SSH al droplet y desplegar
ssh $REMOTE_USER@$REMOTE_HOST << EOF
    set -e

    # Instalar Docker si no existe
    if ! command -v docker &> /dev/null; then
        echo "Installing Docker..."
        curl -fsSL https://get.docker.com | sh
        systemctl enable docker
        systemctl start docker
    fi

    # Instalar docker-compose si no existe
    if ! command -v docker-compose &> /dev/null; then
        echo "Installing docker-compose..."
        apt-get install -y docker-compose-plugin
    fi

    # Clonar o actualizar repo
    if [ -d "$REMOTE_DIR" ]; then
        echo "Updating repository..."
        cd $REMOTE_DIR
        git pull origin main
    else
        echo "Cloning repository..."
        git clone $REPO_URL $REMOTE_DIR
        cd $REMOTE_DIR
    fi

    # Verificar .env
    if [ ! -f ".env" ]; then
        echo "ERROR: .env file not found!"
        echo "Copy .env.example to .env and configure it:"
        echo "  cp .env.example .env && nano .env"
        exit 1
    fi

    # Setear modo
    sed -i "s/^BOT_MODE=.*/BOT_MODE=$MODE/" .env
    echo "Mode set to: $MODE"

    # Crear directorios
    mkdir -p logs models

    # Build y deploy
    echo "Building and deploying..."
    docker compose down scalping-bot 2>/dev/null || true
    docker compose build --no-cache scalping-bot
    docker compose up -d scalping-bot

    # Verificar
    sleep 5
    echo ""
    echo "Container status:"
    docker compose ps scalping-bot
    echo ""
    echo "Recent logs:"
    docker compose logs --tail=20 scalping-bot
EOF

echo ""
echo "═══════════════════════════════════"
echo "  DEPLOY COMPLETE!"
echo "  Check logs: ssh $REMOTE_USER@$REMOTE_HOST 'cd $REMOTE_DIR && docker compose logs -f scalping-bot'"
echo "═══════════════════════════════════"
