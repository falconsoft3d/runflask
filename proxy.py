"""
Proxy inverso simple para el prototipo local de RunFlask.

Resuelve el subdominio en el header Host (p.ej. "mi-proyecto.localhost:8080")
al puerto interno del contenedor Docker del proyecto correspondiente, y
reenvia la peticion HTTP tal cual (streaming) a "http://127.0.0.1:<puerto>".

Uso: python proxy.py
"""
import os

import requests
from dotenv import load_dotenv
from flask import Flask, Response, request

load_dotenv()

from app import create_app  # noqa: E402
from app.models import Project  # noqa: E402

app = create_app()
# static_folder=None evita que Flask registre su propia ruta "/static/<path:filename>",
# que interceptaria (con 404) las peticiones a /static/... de las apps desplegadas.
proxy = Flask("runflask-proxy", static_folder=None)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    # requests/urllib3 ya descomprime el body automaticamente; reenviar esta
    # cabecera haria que el navegador intente des-gzipear contenido ya plano
    # (rompe CSS/JS/imagenes servidas comprimidas).
    "content-encoding",
}


def _extract_subdomain(host_header: str, base_domain: str) -> str:
    host = host_header.split(":")[0].lower()
    suffix = f".{base_domain}"
    if host.endswith(suffix):
        return host[: -len(suffix)]
    return ""


@proxy.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@proxy.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def route_request(path):
    with app.app_context():
        base_domain = app.config["BASE_DOMAIN"]
        subdomain = _extract_subdomain(request.host, base_domain)
        if not subdomain:
            return Response("Especifica un subdominio, p.ej. mi-proyecto.localhost:8080", status=400)

        project = Project.query.filter_by(subdomain=subdomain).first()
        if project is None:
            return Response(f"No existe ningun proyecto para '{subdomain}'", status=404)
        if not project.host_port or project.status != "activo":
            return Response(f"El proyecto '{subdomain}' no esta activo (estado: {project.status}).", status=503)

        target_url = f"http://127.0.0.1:{project.host_port}/{path}"

    forward_headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}

    try:
        upstream = requests.request(
            method=request.method,
            url=target_url,
            headers=forward_headers,
            params=request.args,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True,
            timeout=30,
        )
    except requests.RequestException:
        return Response("El servicio del proyecto no responde.", status=502)

    response_headers = [
        (k, v) for k, v in upstream.raw.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS
    ]
    return Response(upstream.iter_content(chunk_size=8192), status=upstream.status_code, headers=response_headers)


if __name__ == "__main__":
    with app.app_context():
        proxy_port = app.config["PROXY_PORT"]
    proxy.run(host="0.0.0.0", port=proxy_port, debug=False, threaded=True)
