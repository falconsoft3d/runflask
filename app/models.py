import re
import secrets
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def _fernet():
    key = current_app.config.get("FERNET_KEY")
    if not key:
        raise RuntimeError(
            "FERNET_KEY no esta configurada. Genera una con "
            "'python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"' "
            "y agregala a tu .env"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)

    github_id = db.Column(db.String(64), unique=True, nullable=True, index=True)
    github_login = db.Column(db.String(255), nullable=True)
    _github_token_encrypted = db.Column("github_token_encrypted", db.Text, nullable=True)

    is_admin = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    projects = db.relationship("Project", backref="owner", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def github_token(self):
        if not self._github_token_encrypted:
            return None
        try:
            return _fernet().decrypt(self._github_token_encrypted.encode()).decode()
        except InvalidToken:
            return None

    @github_token.setter
    def github_token(self, value):
        if value is None:
            self._github_token_encrypted = None
        else:
            self._github_token_encrypted = _fernet().encrypt(value.encode()).decode()


SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def slugify_subdomain(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:63] or "app"


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    name = db.Column(db.String(255), nullable=False)
    subdomain = db.Column(db.String(63), unique=True, nullable=False, index=True)

    source_type = db.Column(db.String(16), nullable=False, default="github")  # "github" o "local"

    repo_full_name = db.Column(db.String(255), nullable=True)  # "owner/repo"
    repo_clone_url = db.Column(db.String(500), nullable=True)
    default_branch = db.Column(db.String(100), default="main")

    webhook_id = db.Column(db.String(64), nullable=True)
    webhook_secret = db.Column(db.String(64), nullable=False, default=lambda: secrets.token_hex(32))

    container_id = db.Column(db.String(128), nullable=True)
    host_port = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(32), default="creado")  # creado, desplegando, activo, error, detenido

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deployments = db.relationship(
        "Deployment", backref="project", lazy=True, cascade="all, delete-orphan",
        order_by="desc(Deployment.created_at)",
    )

    @property
    def url(self):
        from flask import current_app
        base = current_app.config["BASE_DOMAIN"]
        scheme = current_app.config["PUBLIC_PROJECT_SCHEME"]
        port = current_app.config["PUBLIC_PROJECT_PORT"]
        port_suffix = f":{port}" if port else ""
        return f"{scheme}://{self.subdomain}.{base}{port_suffix}"


class Deployment(db.Model):
    __tablename__ = "deployments"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)

    commit_sha = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), default="en_progreso")  # en_progreso, exitoso, fallido
    log = db.Column(db.Text, default="")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)


class AppSettings(db.Model):
    """Configuracion global de la plataforma. Se espera una unica fila (id=1)."""

    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    registration_enabled = db.Column(db.Boolean, nullable=False, default=True)
    _openai_api_key_encrypted = db.Column("openai_api_key_encrypted", db.Text, nullable=True)

    @property
    def openai_api_key(self):
        if not self._openai_api_key_encrypted:
            return None
        try:
            return _fernet().decrypt(self._openai_api_key_encrypted.encode()).decode()
        except InvalidToken:
            return None

    @openai_api_key.setter
    def openai_api_key(self, value):
        if not value:
            self._openai_api_key_encrypted = None
        else:
            self._openai_api_key_encrypted = _fernet().encrypt(value.encode()).decode()

    @classmethod
    def get(cls) -> "AppSettings":
        settings = db.session.get(cls, 1)
        if settings is None:
            settings = cls(id=1, registration_enabled=True)
            db.session.add(settings)
            db.session.commit()
        return settings
