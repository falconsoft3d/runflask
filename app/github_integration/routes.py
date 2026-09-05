import hashlib
import hmac
import secrets

from flask import Blueprint, current_app, flash, jsonify, redirect, request, session, url_for
from flask_login import current_user, login_required

from app.deploy.service import trigger_deploy_async
from app.extensions import db
from app.github_integration import client as gh
from app.models import Project

github_bp = Blueprint("github", __name__, url_prefix="/github")


@github_bp.route("/connect")
@login_required
def connect():
    state = secrets.token_urlsafe(32)
    session["github_oauth_state"] = state
    url = gh.build_authorize_url(
        current_app.config["GITHUB_CLIENT_ID"],
        current_app.config["GITHUB_OAUTH_CALLBACK_URL"],
        state,
    )
    return redirect(url)


@github_bp.route("/callback")
@login_required
def callback():
    expected_state = session.pop("github_oauth_state", None)
    state = request.args.get("state")
    if not expected_state or not state or not hmac.compare_digest(expected_state, state):
        flash("Estado de OAuth invalido. Intenta conectar de nuevo.", "danger")
        return redirect(url_for("dashboard.index"))

    code = request.args.get("code")
    if not code:
        flash("GitHub no devolvio un codigo de autorizacion.", "danger")
        return redirect(url_for("dashboard.index"))

    try:
        token = gh.exchange_code_for_token(
            current_app.config["GITHUB_CLIENT_ID"],
            current_app.config["GITHUB_CLIENT_SECRET"],
            code,
            current_app.config["GITHUB_OAUTH_CALLBACK_URL"],
        )
        gh_user = gh.get_authenticated_user(token)
    except Exception:
        flash("No se pudo completar la conexion con GitHub.", "danger")
        return redirect(url_for("dashboard.index"))

    current_user.github_id = str(gh_user["id"])
    current_user.github_login = gh_user.get("login")
    current_user.github_token = token
    db.session.commit()

    flash("Cuenta de GitHub conectada correctamente.", "success")
    return redirect(url_for("dashboard.new_project"))


@github_bp.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")
    event = request.headers.get("X-GitHub-Event", "")
    payload = request.get_data()

    repo_full_name = (request.get_json(silent=True) or {}).get("repository", {}).get("full_name")
    if not repo_full_name:
        return jsonify({"error": "payload invalido"}), 400

    project = Project.query.filter_by(repo_full_name=repo_full_name).first()
    if project is None:
        return jsonify({"error": "proyecto no encontrado"}), 404

    expected_sig = "sha256=" + hmac.new(
        project.webhook_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    if not signature or not hmac.compare_digest(expected_sig, signature):
        return jsonify({"error": "firma invalida"}), 401

    if event != "push":
        return jsonify({"status": "ignorado"}), 200

    trigger_deploy_async(current_app._get_current_object(), project.id, project.user_id)
    return jsonify({"status": "deploy iniciado"}), 202
