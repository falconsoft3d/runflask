#!/usr/bin/env bash
#
# Instalador de RunFlask para Ubuntu (22.04+).
# Instala dependencias del sistema, Docker Engine, crea el entorno virtual de
# Python, genera las claves necesarias en .env y configura RunFlask como dos
# servicios systemd (panel de control + proxy inverso).
#
# Uso:
#   sudo ./install.sh
#
# Variables de entorno opcionales para personalizar la instalacion:
#   APP_DIR   Directorio del proyecto (por defecto: directorio donde esta este script)
#   APP_USER  Usuario del sistema que ejecutara los servicios (por defecto: $SUDO_USER o el usuario actual)
#   PANEL_PORT  Puerto del panel de control (por defecto: 5000)
#   PROXY_PORT  Puerto del proxy inverso (por defecto: 8080)

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Este instalador necesita privilegios de root. Ejecuta: sudo ./install.sh" >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "Este instalador es para Ubuntu/Debian (requiere apt-get). No se detecto en este sistema." >&2
  exit 1
fi

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
APP_USER="${APP_USER:-${SUDO_USER:-$(whoami)}}"
PANEL_PORT="${PANEL_PORT:-5000}"
PROXY_PORT="${PROXY_PORT:-8080}"
VENV_DIR="${APP_DIR}/.venv"
ENV_FILE="${APP_DIR}/.env"

log() { echo -e "\n\033[1;32m==> $*\033[0m"; }

log "Instalando en: ${APP_DIR} (usuario de servicio: ${APP_USER})"

# El .env se crea primero y de forma independiente (con python3/openssl del
# sistema, sin depender del venv) para que quede listo aunque algun paso
# posterior (apt-get, instalacion de Docker, etc.) falle.
if [[ ! -f "${ENV_FILE}" ]]; then
  log "Creando .env a partir de .env.example"
  sudo -u "${APP_USER}" cp "${APP_DIR}/.env.example" "${ENV_FILE}"

  if command -v python3 >/dev/null 2>&1; then
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    FERNET_KEY=$(python3 -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
  else
    SECRET_KEY=$(openssl rand -hex 32)
    FERNET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
  fi

  sudo -u "${APP_USER}" sed -i \
    -e "s#^SECRET_KEY=.*#SECRET_KEY=${SECRET_KEY}#" \
    -e "s#^FERNET_KEY=.*#FERNET_KEY=${FERNET_KEY}#" \
    -e "s#^DATABASE_URL=.*#DATABASE_URL=sqlite:////${APP_DIR#/}/runflask.db#" \
    -e "s#^PROXY_PORT=.*#PROXY_PORT=${PROXY_PORT}#" \
    "${ENV_FILE}"
  chown "${APP_USER}" "${ENV_FILE}"

  log "Se genero .env con SECRET_KEY y FERNET_KEY nuevos. Debes completar a mano:"
  echo "    - GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET (OAuth App de GitHub)"
  echo "    - GITHUB_OAUTH_CALLBACK_URL y PUBLIC_WEBHOOK_BASE_URL (tu dominio real)"
  echo "    - BASE_DOMAIN (tu dominio, p.ej. runflask.midominio.com)"
else
  log ".env ya existe, no se sobreescribe"
fi

log "Actualizando indices de paquetes e instalando dependencias del sistema"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip sqlite3 git curl ca-certificates gnupg openssl

if ! command -v docker >/dev/null 2>&1; then
  log "Instalando Docker Engine"
  curl -fsSL https://get.docker.com | sh
else
  log "Docker ya esta instalado, se omite"
fi

log "Agregando ${APP_USER} al grupo docker"
usermod -aG docker "${APP_USER}"
systemctl enable --now docker

log "Creando entorno virtual de Python en ${VENV_DIR}"
sudo -u "${APP_USER}" python3 -m venv "${VENV_DIR}"
sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip
sudo -u "${APP_USER}" "${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt"

sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/workspaces" "${APP_DIR}/instance"

log "Creando servicio systemd runflask-panel (gunicorn, puerto ${PANEL_PORT})"
cat > /etc/systemd/system/runflask-panel.service <<EOF
[Unit]
Description=RunFlask - panel de control
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/gunicorn --workers 2 --bind 0.0.0.0:${PANEL_PORT} run:app
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

log "Creando servicio systemd runflask-proxy (gunicorn, puerto ${PROXY_PORT})"
cat > /etc/systemd/system/runflask-proxy.service <<EOF
[Unit]
Description=RunFlask - proxy inverso de subdominios
After=network.target runflask-panel.service
Requires=docker.service

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/gunicorn --workers 4 --bind 0.0.0.0:${PROXY_PORT} proxy:proxy
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

log "Habilitando e iniciando los servicios"
systemctl daemon-reload
systemctl enable --now runflask-panel.service
systemctl enable --now runflask-proxy.service

log "Instalacion completa"
echo "Panel de control: http://<ip-o-dominio>:${PANEL_PORT}"
echo "Proxy de proyectos: http://<subdominio>.<tu-dominio>:${PROXY_PORT}"
echo
echo "Antes de usarlo en produccion:"
echo "  1. Edita ${ENV_FILE} con tu dominio real y credenciales de GitHub OAuth."
echo "  2. Configura DNS wildcard (*.tu-dominio.com) apuntando a este servidor."
echo "  3. Revisa deploy.md para poner Nginx + Let's Encrypt delante de ambos servicios."
echo "  4. sudo systemctl restart runflask-panel runflask-proxy   # tras cambios en .env"
echo "  5. journalctl -u runflask-panel -f   # ver logs en vivo"
