import os
import threading
from datetime import datetime

from app.deploy.manager import DeployError, build_and_run, clone_or_update_repo, ensure_dockerfile
from app.extensions import db
from app.models import Deployment, Project


def _authenticated_clone_url(repo_clone_url: str, token: str) -> str:
    if token and repo_clone_url.startswith("https://"):
        return repo_clone_url.replace("https://", f"https://x-access-token:{token}@", 1)
    return repo_clone_url


def _project_dir(app, project: Project) -> str:
    return os.path.join(app.config["WORKSPACES_DIR"], str(project.id))


def _container_name(project: Project) -> str:
    return f"runflask-proj-{project.id}"


def _build_and_register(app, project: Project, deployment: Deployment, project_dir: str, log) -> None:
    ensure_dockerfile(project_dir)

    image_tag = f"runflask-proj-{project.id}:latest"
    container_id, host_port = build_and_run(
        project_dir,
        image_tag,
        _container_name(project),
        (app.config["DEPLOY_PORT_RANGE_START"], app.config["DEPLOY_PORT_RANGE_END"]),
        app.config["PROJECT_DOCKER_NETWORK"],
        log_callback=log,
    )

    project.container_id = container_id
    project.host_port = host_port
    project.status = "activo"
    deployment.status = "exitoso"
    log("Deploy completado correctamente.")


def run_deploy(app, project_id: int, user_id: int) -> None:
    """Ejecuta el flujo completo de deploy para un proyecto conectado a GitHub."""
    with app.app_context():
        project = db.session.get(Project, project_id)
        if project is None:
            return

        from app.models import User

        user = db.session.get(User, user_id)
        token = user.github_token if user else None

        deployment = Deployment(project_id=project.id, status="en_progreso", log="")
        db.session.add(deployment)
        project.status = "desplegando"
        db.session.commit()

        log_lines = []

        def log(msg):
            log_lines.append(str(msg))

        try:
            clone_url = _authenticated_clone_url(project.repo_clone_url, token)
            project_dir = _project_dir(app, project)

            log("Clonando/actualizando repositorio...")
            sha = clone_or_update_repo(clone_url, project_dir, project.default_branch or "main")
            deployment.commit_sha = sha

            _build_and_register(app, project, deployment, project_dir, log)
        except DeployError as exc:
            project.status = "error"
            deployment.status = "fallido"
            log(f"ERROR: {exc}")
        except Exception as exc:  # noqa: BLE001 - registrar cualquier fallo inesperado en el log del deploy
            project.status = "error"
            deployment.status = "fallido"
            log(f"ERROR inesperado: {exc}")
        finally:
            deployment.log = "\n".join(log_lines)
            deployment.finished_at = datetime.utcnow()
            db.session.commit()


def run_deploy_local(app, project_id: int) -> None:
    """Reconstruye y corre un proyecto cuyos archivos ya fueron subidos como carpeta/zip local."""
    with app.app_context():
        project = db.session.get(Project, project_id)
        if project is None:
            return

        deployment = Deployment(project_id=project.id, status="en_progreso", log="")
        db.session.add(deployment)
        project.status = "desplegando"
        db.session.commit()

        log_lines = []

        def log(msg):
            log_lines.append(str(msg))

        project_dir = _project_dir(app, project)
        try:
            if not os.path.isdir(project_dir):
                raise DeployError("No se encontraron archivos del proyecto subidos.")

            log("Usando los archivos locales subidos...")
            _build_and_register(app, project, deployment, project_dir, log)
        except DeployError as exc:
            project.status = "error"
            deployment.status = "fallido"
            log(f"ERROR: {exc}")
        except Exception as exc:  # noqa: BLE001 - registrar cualquier fallo inesperado en el log del deploy
            project.status = "error"
            deployment.status = "fallido"
            log(f"ERROR inesperado: {exc}")
        finally:
            deployment.log = "\n".join(log_lines)
            deployment.finished_at = datetime.utcnow()
            db.session.commit()


def trigger_deploy_async(app, project_id: int, user_id: int) -> None:
    thread = threading.Thread(target=run_deploy, args=(app, project_id, user_id), daemon=True)
    thread.start()


def trigger_local_deploy_async(app, project_id: int) -> None:
    thread = threading.Thread(target=run_deploy_local, args=(app, project_id), daemon=True)
    thread.start()

