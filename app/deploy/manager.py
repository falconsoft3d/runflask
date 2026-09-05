import os
import shutil
import socket
import subprocess

import docker
from docker.errors import DockerException, NotFound

DEFAULT_DOCKERFILE = """\
FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
RUN pip install --no-cache-dir gunicorn
ENV PORT=5000
EXPOSE 5000
CMD ["sh", "-c", "if [ -f app.py ]; then gunicorn -b 0.0.0.0:5000 app:app; elif [ -f wsgi.py ]; then gunicorn -b 0.0.0.0:5000 wsgi:app; elif [ -f run.py ]; then gunicorn -b 0.0.0.0:5000 run:app; else echo 'No se encontro app.py, wsgi.py ni run.py en /app' >&2; exit 1; fi"]
"""


class DeployError(Exception):
    pass


def _run_git(args, cwd=None):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise DeployError(f"git {' '.join(args)} fallo: {result.stderr.strip()}")
    return result.stdout


def clone_or_update_repo(clone_url: str, dest_dir: str, branch: str = "main") -> str:
    """Clona el repo si no existe, o hace pull si ya existe. Devuelve el commit SHA."""
    if os.path.isdir(os.path.join(dest_dir, ".git")):
        _run_git(["fetch", "origin", branch], cwd=dest_dir)
        _run_git(["checkout", branch], cwd=dest_dir)
        _run_git(["reset", "--hard", f"origin/{branch}"], cwd=dest_dir)
    else:
        os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir)
        _run_git(["clone", "--branch", branch, "--single-branch", clone_url, dest_dir])

    sha = _run_git(["rev-parse", "HEAD"], cwd=dest_dir).strip()
    return sha


def ensure_dockerfile(project_dir: str) -> None:
    dockerfile_path = os.path.join(project_dir, "Dockerfile")
    if not os.path.isfile(dockerfile_path):
        with open(dockerfile_path, "w") as f:
            f.write(DEFAULT_DOCKERFILE)


def find_free_port(start: int, end: int) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise DeployError("No hay puertos libres disponibles en el rango configurado.")


def build_and_run(
    project_dir: str,
    image_tag: str,
    container_name: str,
    port_range: tuple,
    log_callback=None,
) -> tuple:
    """Construye la imagen Docker y corre el contenedor. Devuelve (container_id, host_port)."""

    def log(msg):
        if log_callback:
            log_callback(msg)

    try:
        client = docker.from_env()
    except DockerException as exc:
        raise DeployError(f"No se pudo conectar con Docker: {exc}") from exc

    log(f"Construyendo imagen {image_tag}...")
    try:
        _, build_logs = client.images.build(path=project_dir, tag=image_tag, rm=True)
        for chunk in build_logs:
            if "stream" in chunk:
                log(chunk["stream"].rstrip())
    except DockerException as exc:
        raise DeployError(f"Fallo al construir la imagen: {exc}") from exc

    # Elimina el contenedor anterior del proyecto, si existe
    try:
        old = client.containers.get(container_name)
        log("Deteniendo contenedor anterior...")
        old.remove(force=True)
    except NotFound:
        pass

    host_port = find_free_port(port_range[0], port_range[1])
    log(f"Iniciando contenedor en el puerto {host_port}...")

    try:
        container = client.containers.run(
            image_tag,
            name=container_name,
            detach=True,
            ports={"5000/tcp": host_port},
            mem_limit="256m",
            nano_cpus=1_000_000_000,  # 1 CPU
            restart_policy={"Name": "unless-stopped"},
        )
    except DockerException as exc:
        raise DeployError(f"Fallo al iniciar el contenedor: {exc}") from exc

    return container.id, host_port


def stop_project_container(container_name: str) -> None:
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        container.remove(force=True)
    except (DockerException, NotFound):
        pass
