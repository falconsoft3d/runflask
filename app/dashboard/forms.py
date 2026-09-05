from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, Regexp

SUBDOMAIN_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
RELATIVE_PATH_PATTERN = r"^[^/][^\x00]*$"


class NewProjectForm(FlaskForm):
    repo_full_name = SelectField("Repositorio de GitHub", validators=[DataRequired()])
    subdomain = StringField(
        "Subdominio",
        validators=[
            DataRequired(),
            Length(min=1, max=63),
            Regexp(SUBDOMAIN_PATTERN, message="Solo letras minusculas, numeros y guiones."),
        ],
    )
    submit = SubmitField("Conectar y desplegar")


class LocalUploadForm(FlaskForm):
    name = StringField("Nombre del proyecto", validators=[DataRequired(), Length(min=1, max=255)])
    subdomain = StringField(
        "Subdominio",
        validators=[
            DataRequired(),
            Length(min=1, max=63),
            Regexp(SUBDOMAIN_PATTERN, message="Solo letras minusculas, numeros y guiones."),
        ],
    )
    project_zip = FileField(
        "Carpeta del proyecto (.zip)",
        validators=[FileRequired(message="Selecciona un archivo .zip"), FileAllowed(["zip"], "Solo archivos .zip")],
    )
    submit = SubmitField("Subir y desplegar")


class ReuploadForm(FlaskForm):
    project_zip = FileField(
        "Nueva version (.zip)",
        validators=[FileRequired(message="Selecciona un archivo .zip"), FileAllowed(["zip"], "Solo archivos .zip")],
    )
    submit = SubmitField("Subir nueva version")


class OpenAISettingsForm(FlaskForm):
    api_key = PasswordField("API key de OpenAI", validators=[Optional(), Length(max=255)])
    submit_openai = SubmitField("Guardar API key")


class AIEditForm(FlaskForm):
    target_file = StringField(
        "Archivo a editar (ruta relativa dentro del proyecto)",
        validators=[
            DataRequired(),
            Length(max=255),
            Regexp(RELATIVE_PATH_PATTERN, message="Ruta invalida: no debe empezar con '/'."),
        ],
    )
    prompt = TextAreaField("Instruccion para la IA", validators=[DataRequired(), Length(max=4000)])
    image = FileField(
        "Imagen de referencia (opcional)",
        validators=[Optional(), FileAllowed(["png", "jpg", "jpeg", "webp", "gif"], "Formato de imagen no soportado.")],
    )
    submit_ai_generate = SubmitField("Generar propuesta con IA")


class AIApplyForm(FlaskForm):
    target_file = StringField(validators=[DataRequired(), Length(max=255)])
    content = TextAreaField("Contenido propuesto", validators=[DataRequired()])
    submit_ai_apply = SubmitField("Aplicar cambios y redesplegar")
