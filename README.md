# RunFlask

Plataforma tipo Vercel para desplegar proyectos Flask automáticamente desde GitHub.
Los usuarios se registran, conectan su cuenta de GitHub, eligen un repositorio y
la plataforma construye una imagen Docker, la ejecuta y expone el proyecto en un
subdominio propio (p. ej. `mi-proyecto.localhost:8080`). Cada `git push` dispara
un nuevo deploy automático vía webhook.

## Arquitectura

- **Panel de control** (`run.py` / paquete `app/`): Flask + SQLAlchemy + Jinja2.
  Registro/login, conexión OAuth con GitHub, listado de repos, creación de
  proyectos y visualización del historial de deploys.
- **Motor de deploy** (`app/deploy/`): clona/actualiza el repo, genera un
  `Dockerfile` genérico si el repo no trae uno, construye la imagen con el SDK
  de Docker y corre el contenedor en un puerto interno libre.
- **Webhook** (`app/github_integration/routes.py`): recibe los eventos `push`
  de GitHub (firma HMAC verificada), dispara el deploy en un hilo en segundo
  plano.
- **Proxy inverso** (`proxy.py`): proceso aparte que escucha en `PROXY_PORT`,
  resuelve el subdominio del `Host` recibido y reenvía la petición al
  contenedor correspondiente.

## Requisitos

- Python 3.11+
- Docker Desktop (o Docker Engine) corriendo localmente
- Una GitHub OAuth App (para login/listado de repos y webhooks)

## Puesta en marcha

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Genera una clave Fernet para cifrar los tokens de GitHub guardados en BD:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Pega el resultado en FERNET_KEY dentro de .env

# Crea una OAuth App en https://github.com/settings/developers
#   Homepage URL: http://localhost:5000
#   Authorization callback URL: http://localhost:5000/github/callback
# Copia el Client ID y Client Secret a .env
```

Para que GitHub pueda entregar los webhooks de `push` necesitas una URL
pública (por ejemplo con `ngrok http 5000`) y colocarla en
`PUBLIC_WEBHOOK_BASE_URL`.

### Ejecutar la plataforma

En dos terminales separadas:

```bash
# Terminal 1: panel de control (registro, login, dashboard, OAuth, webhook)
python run.py

# Terminal 2: proxy que sirve los subdominios de los proyectos desplegados
python proxy.py
```

Abre `http://localhost:5000`, regístrate, conecta GitHub y crea tu primer
proyecto. Una vez que el deploy termine, tu app estará disponible en
`http://<subdominio>.localhost:8080`.

## Notas de seguridad

- Los tokens de acceso de GitHub se cifran con Fernet antes de guardarse en BD.
- Los webhooks se validan con HMAC-SHA256 usando un secreto único por proyecto.
- El OAuth usa el parámetro `state` para prevenir CSRF.
- Los formularios usan protección CSRF (Flask-WTF); el endpoint de webhook está
  exento porque lo invoca GitHub directamente, no un navegador con sesión.
- Cada proyecto corre en su propio contenedor con límites de memoria/CPU.

## Limitaciones del prototipo

- Pensado para correr en `localhost`; para producción real se necesita DNS
  wildcard, TLS y un proxy inverso más robusto (nginx/Traefik) en lugar de
  `proxy.py`.
- Un solo contenedor por proyecto (sin escalado horizontal ni zero-downtime
  deploys).

## Despliegue en un servidor Ubuntu

Para instalar RunFlask en un servidor Ubuntu real (con systemd, Gunicorn y
opcionalmente Nginx + HTTPS), usa el instalador incluido:

```bash
sudo ./install.sh
```

Ver [deploy.md](deploy.md) para la guía completa (requisitos, configuración
post-instalación, Nginx/Let's Encrypt, actualización y desinstalación).

