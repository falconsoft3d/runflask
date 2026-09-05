import base64

import requests

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
REQUEST_TIMEOUT = 60
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}


class AIEditError(Exception):
    pass


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def generate_file_edit(
    api_key: str,
    relative_path: str,
    current_content: str,
    prompt: str,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
) -> str:
    """Pide a un modelo de OpenAI el nuevo contenido completo de un archivo del
    proyecto, en base al contenido actual, una instruccion en texto y (opcional)
    una imagen de referencia. Devuelve el contenido propuesto sin aplicarlo."""
    if not api_key:
        raise AIEditError("No hay una API key de OpenAI configurada. Pidele al administrador que la agregue en Configuracion.")

    if image_bytes is not None:
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise AIEditError("La imagen supera el tamano maximo permitido (8 MB).")
        if image_mime not in ALLOWED_IMAGE_MIME:
            raise AIEditError("Formato de imagen no soportado (usa PNG, JPEG, WEBP o GIF).")

    instructions = (
        "Eres un asistente que edita archivos de un proyecto Flask. "
        f"Se te da el contenido actual del archivo '{relative_path}' y una instruccion del usuario. "
        "Responde UNICAMENTE con el contenido completo y final del archivo ya modificado, "
        "sin explicaciones, sin markdown, sin bloques de codigo delimitados por ```."
    )

    user_content = [
        {
            "type": "text",
            "text": (
                f"Instruccion: {prompt}\n\n"
                f"Contenido actual de '{relative_path}':\n{current_content}"
            ),
        }
    ]
    if image_bytes is not None:
        encoded = base64.b64encode(image_bytes).decode()
        user_content.append(
            {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{encoded}"}}
        )

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }

    try:
        resp = requests.post(
            OPENAI_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise AIEditError(f"No se pudo contactar a OpenAI: {exc}") from exc

    if resp.status_code == 401:
        raise AIEditError("La API key de OpenAI no es valida.")
    if not resp.ok:
        raise AIEditError(f"OpenAI respondio con un error ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise AIEditError("Respuesta inesperada de OpenAI.") from exc

    return _strip_code_fence(content)
