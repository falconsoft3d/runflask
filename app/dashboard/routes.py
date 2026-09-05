import os
from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.ai import client as ai_client
from app.auth.forms import ChangePasswordForm, ProfileForm
from app.dashboard.forms import AIApplyForm, AIEditForm, LocalUploadForm, NewProjectForm, OpenAISettingsForm, ReuploadForm
from app.deploy.local_upload import UploadError, extract_zip_safely
from app.deploy.manager import stop_project_container
from app.deploy.service import _project_dir, trigger_deploy_async, trigger_local_deploy_async
from app.extensions import db
from app.github_integration import client as gh
from app.models import AppSettings, Project, User

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@dashboard_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    app_settings = AppSettings.get()
    openai_form = OpenAISettingsForm()

    if request.method == "POST" and request.form.get("action") == "toggle_registration":
        app_settings.registration_enabled = not app_settings.registration_enabled
        db.session.commit()
        flash(
            "Registro de nuevas cuentas "
            + ("habilitado." if app_settings.registration_enabled else "deshabilitado."),
            "success",
        )
        return redirect(url_for("dashboard.settings"))

    if openai_form.submit_openai.data and openai_form.validate_on_submit():
        app_settings.openai_api_key = openai_form.api_key.data.strip() or None
        db.session.commit()
        flash("API key de OpenAI actualizada.", "success")
        return redirect(url_for("dashboard.settings"))

    return render_template("dashboard/settings.html", app_settings=app_settings, openai_form=openai_form)


@dashboard_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    profile_form = ProfileForm(prefix="profile", obj=current_user)
    password_form = ChangePasswordForm(prefix="password")

    if profile_form.submit_profile.data and profile_form.validate_on_submit():
        new_email = profile_form.email.data.strip().lower()
        existing = User.query.filter(User.email == new_email, User.id != current_user.id).first()
        if existing:
            flash("Ese correo ya esta en uso por otra cuenta.", "danger")
        else:
            current_user.email = new_email
            db.session.commit()
            flash("Datos de perfil actualizados.", "success")
        return redirect(url_for("dashboard.profile"))

    if password_form.submit_password.data and password_form.validate_on_submit():
        if not current_user.check_password(password_form.current_password.data):
            flash("La contrasena actual no es correcta.", "danger")
        else:
            current_user.set_password(password_form.new_password.data)
            db.session.commit()
            flash("Contrasena actualizada correctamente.", "success")
        return redirect(url_for("dashboard.profile"))

    if not profile_form.is_submitted():
        profile_form.email.data = current_user.email

    return render_template("dashboard/profile.html", profile_form=profile_form, password_form=password_form)


@dashboard_bp.route("/")
@login_required
def index():
    projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.created_at.desc()).all()
    return render_template("dashboard/index.html", projects=projects)


@dashboard_bp.route("/projects/new", methods=["GET", "POST"])
@login_required
def new_project():
    repos = []
    if current_user.github_token:
        try:
            repos = gh.list_user_repos(current_user.github_token)
        except Exception:
            flash("No se pudieron obtener tus repositorios de GitHub.", "danger")

    form = NewProjectForm()
    form.repo_full_name.choices = [(r["full_name"], r["full_name"]) for r in repos]
    repo_by_name = {r["full_name"]: r for r in repos}
    local_form = LocalUploadForm()

    if form.is_submitted() and form.submit.data:
        if not current_user.github_token:
            flash("Primero conecta tu cuenta de GitHub.", "info")
            return redirect(url_for("github.connect"))

        if form.validate_on_submit():
            subdomain = form.subdomain.data.strip().lower()
            if Project.query.filter_by(subdomain=subdomain).first():
                flash("Ese subdominio ya esta en uso, elige otro.", "danger")
                return render_template("dashboard/new_project.html", form=form, local_form=local_form)

            repo = repo_by_name.get(form.repo_full_name.data)
            if repo is None:
                flash("Repositorio invalido.", "danger")
                return render_template("dashboard/new_project.html", form=form, local_form=local_form)

            project = Project(
                user_id=current_user.id,
                name=repo["name"],
                subdomain=subdomain,
                source_type="github",
                repo_full_name=repo["full_name"],
                repo_clone_url=repo["clone_url"],
                default_branch=repo.get("default_branch") or "main",
            )
            db.session.add(project)
            db.session.commit()

            webhook_url = f"{current_app.config['PUBLIC_WEBHOOK_BASE_URL']}/github/webhook"
            try:
                hook = gh.create_webhook(current_user.github_token, repo["full_name"], webhook_url, project.webhook_secret)
                project.webhook_id = str(hook.get("id"))
                db.session.commit()
            except Exception:
                flash(
                    "Proyecto creado, pero no se pudo registrar el webhook automatico. "
                    "Puedes desplegar manualmente desde el panel.",
                    "warning",
                )

            trigger_deploy_async(current_app._get_current_object(), project.id, current_user.id)
            flash("Proyecto creado. El primer deploy esta en progreso.", "success")
            return redirect(url_for("dashboard.project_detail", project_id=project.id))

    return render_template("dashboard/new_project.html", form=form, local_form=local_form)


@dashboard_bp.route("/projects/new-local", methods=["GET", "POST"])
@login_required
def new_project_local():
    form = LocalUploadForm()

    if form.validate_on_submit():
        subdomain = form.subdomain.data.strip().lower()
        if Project.query.filter_by(subdomain=subdomain).first():
            flash("Ese subdominio ya esta en uso, elige otro.", "danger")
            return render_template("dashboard/new_project.html", local_form=form, form=NewProjectForm())

        project = Project(
            user_id=current_user.id,
            name=form.name.data.strip(),
            subdomain=subdomain,
            source_type="local",
        )
        db.session.add(project)
        db.session.commit()

        app = current_app._get_current_object()
        try:
            extract_zip_safely(form.project_zip.data, _project_dir(app, project))
        except UploadError as exc:
            db.session.delete(project)
            db.session.commit()
            flash(str(exc), "danger")
            return redirect(url_for("dashboard.new_project_local"))

        trigger_local_deploy_async(app, project.id)
        flash("Proyecto subido. El primer deploy esta en progreso.", "success")
        return redirect(url_for("dashboard.project_detail", project_id=project.id))

    return render_template("dashboard/new_project.html", local_form=form, form=NewProjectForm())


@dashboard_bp.route("/projects/<int:project_id>")
@login_required
def project_detail(project_id):
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if project is None:
        abort(404)
    reupload_form = ReuploadForm() if project.source_type == "local" else None
    ai_form = AIEditForm()
    return render_template(
        "dashboard/project_detail.html",
        project=project,
        reupload_form=reupload_form,
        ai_form=ai_form,
        ai_apply_form=None,
    )


@dashboard_bp.route("/projects/<int:project_id>/upload", methods=["POST"])
@login_required
def upload_new_version(project_id):
    project = Project.query.filter_by(id=project_id, user_id=current_user.id, source_type="local").first()
    if project is None:
        abort(404)

    form = ReuploadForm()
    if not form.validate_on_submit():
        flash("Selecciona un archivo .zip valido.", "danger")
        return redirect(url_for("dashboard.project_detail", project_id=project.id))

    app = current_app._get_current_object()
    try:
        extract_zip_safely(form.project_zip.data, _project_dir(app, project))
    except UploadError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("dashboard.project_detail", project_id=project.id))

    trigger_local_deploy_async(app, project.id)
    flash("Nueva version subida. Deploy en progreso.", "info")
    return redirect(url_for("dashboard.project_detail", project_id=project.id))


def _resolve_project_file(project_dir, relative_path):
    """Resuelve una ruta relativa dentro del proyecto, evitando path traversal."""
    target = os.path.abspath(os.path.join(project_dir, relative_path))
    project_dir_abs = os.path.abspath(project_dir)
    if os.path.commonpath([project_dir_abs, target]) != project_dir_abs:
        raise ValueError("Ruta de archivo invalida.")
    return target


@dashboard_bp.route("/projects/<int:project_id>/ai-edit", methods=["POST"])
@login_required
def ai_generate(project_id):
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if project is None:
        abort(404)

    reupload_form = ReuploadForm() if project.source_type == "local" else None
    ai_form = AIEditForm()

    if not ai_form.validate_on_submit():
        flash("Revisa los datos del formulario de IA.", "danger")
        return render_template(
            "dashboard/project_detail.html", project=project, reupload_form=reupload_form, ai_form=ai_form, ai_apply_form=None
        )

    app = current_app._get_current_object()
    project_dir = _project_dir(app, project)
    try:
        target_path = _resolve_project_file(project_dir, ai_form.target_file.data.strip())
    except ValueError:
        flash("Ruta de archivo invalida.", "danger")
        return redirect(url_for("dashboard.project_detail", project_id=project.id))

    if not os.path.isfile(target_path):
        flash("El archivo indicado no existe en el proyecto.", "danger")
        return redirect(url_for("dashboard.project_detail", project_id=project.id))

    with open(target_path, "r", encoding="utf-8", errors="replace") as f:
        current_content = f.read()

    image_bytes = None
    image_mime = None
    if ai_form.image.data:
        image_bytes = ai_form.image.data.read()
        image_mime = ai_form.image.data.mimetype

    api_key = AppSettings.get().openai_api_key
    try:
        generated = ai_client.generate_file_edit(
            api_key, ai_form.target_file.data.strip(), current_content, ai_form.prompt.data, image_bytes, image_mime
        )
    except ai_client.AIEditError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("dashboard.project_detail", project_id=project.id))

    ai_apply_form = AIApplyForm(target_file=ai_form.target_file.data.strip(), content=generated)
    return render_template(
        "dashboard/project_detail.html",
        project=project,
        reupload_form=reupload_form,
        ai_form=AIEditForm(),
        ai_apply_form=ai_apply_form,
    )


@dashboard_bp.route("/projects/<int:project_id>/ai-apply", methods=["POST"])
@login_required
def ai_apply(project_id):
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if project is None:
        abort(404)

    form = AIApplyForm()
    if not form.validate_on_submit():
        flash("No se pudo aplicar el cambio propuesto.", "danger")
        return redirect(url_for("dashboard.project_detail", project_id=project.id))

    app = current_app._get_current_object()
    project_dir = _project_dir(app, project)
    try:
        target_path = _resolve_project_file(project_dir, form.target_file.data.strip())
    except ValueError:
        flash("Ruta de archivo invalida.", "danger")
        return redirect(url_for("dashboard.project_detail", project_id=project.id))

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(form.content.data)

    # Tras un edit con IA siempre se reconstruye desde los archivos locales del
    # workspace (no se re-clona), para no perder el cambio aplicado.
    trigger_local_deploy_async(app, project.id)
    flash("Cambio aplicado. Redesplegando el proyecto...", "success")
    return redirect(url_for("dashboard.project_detail", project_id=project.id))


@dashboard_bp.route("/projects/<int:project_id>/redeploy", methods=["POST"])
@login_required
def redeploy(project_id):
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if project is None:
        abort(404)

    app = current_app._get_current_object()
    if project.source_type == "local":
        trigger_local_deploy_async(app, project.id)
    else:
        trigger_deploy_async(app, project.id, current_user.id)
    flash("Deploy iniciado.", "info")
    return redirect(url_for("dashboard.project_detail", project_id=project.id))


@dashboard_bp.route("/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if project is None:
        abort(404)

    stop_project_container(f"runflask-proj-{project.id}")

    if project.webhook_id and current_user.github_token:
        try:
            gh.delete_webhook(current_user.github_token, project.repo_full_name, project.webhook_id)
        except Exception:
            pass

    db.session.delete(project)
    db.session.commit()
    flash("Proyecto eliminado.", "info")
    return redirect(url_for("dashboard.index"))
