import os

from flask import Flask, render_template

from app.extensions import csrf, db, login_manager
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(app.config["WORKSPACES_DIR"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.github_integration.routes import github_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(github_bp)

    # El webhook lo llama GitHub directamente (sin sesion de navegador), no aplica CSRF
    csrf.exempt(github_bp)

    with app.app_context():
        db.create_all()

    @app.route("/")
    def root():
        return render_template("landing.html")

    @app.context_processor
    def inject_globals():
        from app.models import AppSettings

        public_project_port = app.config["PUBLIC_PROJECT_PORT"]
        public_project_port_suffix = f":{public_project_port}" if public_project_port else ""

        return {
            "base_domain": app.config["BASE_DOMAIN"],
            "public_project_port_suffix": public_project_port_suffix,
            "registration_enabled": AppSettings.get().registration_enabled,
        }

    return app
