# Despliegue de RunFlask en Ubuntu

Esta guía instala RunFlask en un servidor Ubuntu (22.04+) como dos servicios
`systemd` (panel de control + proxy inverso), usando Gunicorn en vez del
servidor de desarrollo de Flask, y deja preparado el terreno para ponerlo
detrás de Nginx con HTTPS y subdominios reales.

## 1. Requisitos previos

- Un servidor Ubuntu 22.04+ con acceso `sudo`.
- Un dominio propio con capacidad de crear un registro **wildcard** DNS
  (`*.runflask.midominio.com` → IP del servidor) si quieres subdominios reales
  por proyecto. Sin esto, RunFlask sigue funcionando pero solo con
  `localhost`/la IP del servidor.
- Una [OAuth App de GitHub](https://github.com/settings/developers) si vas a
  usar la integración con GitHub (login OAuth + webhooks).
- Puertos abiertos en el firewall: `5000` (panel) y `8080` (proxy), o `80`/`443`
  si pones Nginx delante (recomendado, ver sección 5).

## 2. Instalación con el script

```bash
git clone <url-de-tu-fork-o-repo> runflask
cd runflask
sudo ./install.sh
```

El script (`install.sh`):

1. Instala paquetes del sistema: `python3`, `python3-venv`, `pip`, `sqlite3`,
   `git`, `curl`.
2. Instala Docker Engine (script oficial `get.docker.com`) si no está presente,
   y agrega el usuario de servicio al grupo `docker`.
3. Crea el entorno virtual en `.venv` e instala `requirements.txt` (incluye
   `gunicorn`).
4. Genera `.env` a partir de `.env.example` con `SECRET_KEY` y `FERNET_KEY`
   nuevos generados automáticamente, y ajusta `DATABASE_URL` a una ruta
   absoluta dentro del proyecto.
5. Crea y habilita dos servicios `systemd`:
   - `runflask-panel.service` → Gunicorn sirviendo `run:app` en el puerto `5000`.
   - `runflask-proxy.service` → Gunicorn sirviendo `proxy:proxy` en el puerto `8080`.

Variables opcionales antes de ejecutar el script:

```bash
sudo APP_DIR=/opt/runflask APP_USER=runflask PANEL_PORT=5000 PROXY_PORT=8080 ./install.sh
```

## 3. Configuración posterior obligatoria

Edita `.env` (en la raíz del proyecto) y completa:

```bash
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_OAUTH_CALLBACK_URL=https://runflask.midominio.com/github/callback
PUBLIC_WEBHOOK_BASE_URL=https://runflask.midominio.com
BASE_DOMAIN=runflask.midominio.com
```

En tu OAuth App de GitHub, la **Authorization callback URL** debe coincidir
exactamente con `GITHUB_OAUTH_CALLBACK_URL`.

Tras editar `.env`, reinicia los servicios:

```bash
sudo systemctl restart runflask-panel runflask-proxy
```

## 4. Administrar los servicios

```bash
sudo systemctl status runflask-panel runflask-proxy
sudo systemctl restart runflask-panel runflask-proxy
sudo journalctl -u runflask-panel -f     # logs en vivo del panel
sudo journalctl -u runflask-proxy -f     # logs en vivo del proxy
```

## 5. (Recomendado) Nginx + HTTPS delante de RunFlask

En producción, no expongas Gunicorn directamente a internet. Pon Nginx delante
como proxy TLS-terminating para el panel y para el proxy de subdominios.

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
```

Certificado wildcard (requiere validación DNS, no HTTP, porque cubre
`*.runflask.midominio.com`):

```bash
sudo certbot certonly --manual --preferred-challenges dns \
  -d "runflask.midominio.com" -d "*.runflask.midominio.com"
```

Configuración de Nginx (`/etc/nginx/sites-available/runflask`):

```nginx
# Panel de control
server {
    listen 443 ssl;
    server_name runflask.midominio.com;

    ssl_certificate     /etc/letsencrypt/live/runflask.midominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/runflask.midominio.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Subdominios de proyectos desplegados
server {
    listen 443 ssl;
    server_name *.runflask.midominio.com;

    ssl_certificate     /etc/letsencrypt/live/runflask.midominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/runflask.midominio.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Redirige HTTP a HTTPS
server {
    listen 80;
    server_name runflask.midominio.com *.runflask.midominio.com;
    return 301 https://$host$request_uri;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/runflask /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Con esto, `BASE_DOMAIN=runflask.midominio.com` y `PROXY_PORT` puede seguir
apuntando internamente a `8080` (Nginx ya expone el `443` público).

## 6. Actualizar RunFlask

```bash
cd /ruta/a/runflask
git pull
sudo -u <APP_USER> .venv/bin/pip install -r requirements.txt
sudo systemctl restart runflask-panel runflask-proxy
```

Si hubo cambios en `app/models.py` (columnas nuevas), aplica la migración
manual correspondiente con `sqlite3 runflask.db "ALTER TABLE ... ADD COLUMN ..."`
antes de reiniciar (este proyecto no usa Alembic).

## 7. Notas de seguridad para producción

- El usuario que corre los servicios queda en el grupo `docker`, lo cual
  equivale a acceso root de facto (puede montar cualquier ruta del host en un
  contenedor). Usa una máquina dedicada para RunFlask, no un servidor
  compartido con otras cargas sensibles.
- `SECRET_KEY` y `FERNET_KEY` se generan una sola vez en la instalación;
  consérvalos si migras de servidor (rotar `FERNET_KEY` invalida los tokens de
  GitHub ya cifrados en la base de datos).
- Activa `SESSION_COOKIE_SECURE=true` en `.env` una vez que sirvas todo por
  HTTPS.
- Limita quién puede registrarse usando "Configuración → Registro de nuevas
  cuentas" (deshabilítalo después de crear las cuentas necesarias).
- Haz backups periódicos de `runflask.db` y de la carpeta `workspaces/`.

## 8. Desinstalar

```bash
sudo systemctl disable --now runflask-panel runflask-proxy
sudo rm /etc/systemd/system/runflask-panel.service /etc/systemd/system/runflask-proxy.service
sudo systemctl daemon-reload
docker ps -a --filter "name=runflask-proj-" -q | xargs -r docker rm -f
```
