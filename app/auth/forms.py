from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length


class RegisterForm(FlaskForm):
    email = StringField("Correo electronico", validators=[DataRequired(), Email()])
    password = PasswordField("Contrasena", validators=[DataRequired(), Length(min=8)])
    confirm = PasswordField(
        "Confirmar contrasena", validators=[DataRequired(), EqualTo("password", message="Las contrasenas no coinciden")]
    )
    submit = SubmitField("Crear cuenta")


class LoginForm(FlaskForm):
    email = StringField("Correo electronico", validators=[DataRequired(), Email()])
    password = PasswordField("Contrasena", validators=[DataRequired()])
    submit = SubmitField("Iniciar sesion")


class ProfileForm(FlaskForm):
    email = StringField("Correo electronico", validators=[DataRequired(), Email()])
    submit_profile = SubmitField("Guardar cambios")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Contrasena actual", validators=[DataRequired()])
    new_password = PasswordField("Nueva contrasena", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        "Confirmar nueva contrasena",
        validators=[DataRequired(), EqualTo("new_password", message="Las contrasenas no coinciden")],
    )
    submit_password = SubmitField("Cambiar contrasena")

