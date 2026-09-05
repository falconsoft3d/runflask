from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth.forms import LoginForm, RegisterForm
from app.extensions import db
from app.models import AppSettings, User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next_url(target):
    # Solo permite redirecciones relativas para evitar open redirect
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.netloc or parsed.scheme:
        return None
    return target


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    is_first_user = User.query.count() == 0
    if not is_first_user and not AppSettings.get().registration_enabled:
        flash("El registro de nuevas cuentas esta deshabilitado.", "info")
        return redirect(url_for("auth.login"))

    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            flash("Ya existe una cuenta con ese correo.", "danger")
            return render_template("auth/register.html", form=form)

        user = User(email=email, is_admin=is_first_user)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Cuenta creada correctamente.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()

        # Mensaje generico para no revelar si el correo existe (mitiga user enumeration)
        if user is None or not user.check_password(form.password.data):
            flash("Correo o contrasena incorrectos.", "danger")
            return render_template("auth/login.html", form=form)

        login_user(user)
        next_url = _safe_next_url(request.args.get("next"))
        return redirect(next_url or url_for("dashboard.index"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesion cerrada.", "info")
    return redirect(url_for("auth.login"))
