import os
from urllib.parse import urlparse

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(basedir, "runflask.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    FERNET_KEY = os.environ.get("FERNET_KEY", "")

    GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
    GITHUB_OAUTH_CALLBACK_URL = os.environ.get(
        "GITHUB_OAUTH_CALLBACK_URL", "http://localhost:5000/github/callback"
    )
    PUBLIC_WEBHOOK_BASE_URL = os.environ.get(
        "PUBLIC_WEBHOOK_BASE_URL", "http://localhost:5000"
    )

    BASE_DOMAIN = os.environ.get("BASE_DOMAIN", "localhost")
    PROXY_PORT = int(os.environ.get("PROXY_PORT", 8080))
    _PUBLIC_WEBHOOK_URL = urlparse(PUBLIC_WEBHOOK_BASE_URL)
    PUBLIC_PROJECT_SCHEME = os.environ.get("PUBLIC_PROJECT_SCHEME") or _PUBLIC_WEBHOOK_URL.scheme or "http"
    _PUBLIC_PROJECT_PORT = os.environ.get("PUBLIC_PROJECT_PORT")
    if _PUBLIC_PROJECT_PORT is None:
        PUBLIC_PROJECT_PORT = _PUBLIC_WEBHOOK_URL.port if _PUBLIC_WEBHOOK_URL.netloc else PROXY_PORT
    elif _PUBLIC_PROJECT_PORT.strip() == "":
        PUBLIC_PROJECT_PORT = None
    else:
        PUBLIC_PROJECT_PORT = int(_PUBLIC_PROJECT_PORT)

    DEPLOY_PORT_RANGE_START = int(os.environ.get("DEPLOY_PORT_RANGE_START", 20000))
    DEPLOY_PORT_RANGE_END = int(os.environ.get("DEPLOY_PORT_RANGE_END", 21000))
    PROJECT_DOCKER_NETWORK = os.environ.get("PROJECT_DOCKER_NETWORK", "runflask-net")

    WORKSPACES_DIR = os.path.join(basedir, "workspaces")

    # Limite de tamano de subida (protege contra DoS por archivos zip enormes)
    MAX_CONTENT_LENGTH = 250 * 1024 * 1024  # 250 MB

    # Cookies de sesion seguras por defecto; en produccion detras de HTTPS activar SESSION_COOKIE_SECURE
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

    WTF_CSRF_TIME_LIMIT = None
