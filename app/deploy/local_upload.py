import os
import shutil
import zipfile

MAX_UNCOMPRESSED_SIZE = int(os.environ.get("LOCAL_UPLOAD_MAX_UNCOMPRESSED_MB", 200)) * 1024 * 1024
MAX_FILES = int(os.environ.get("LOCAL_UPLOAD_MAX_FILES", 5000))
JUNK_FILE_NAMES = {".DS_Store"}
JUNK_DIR_NAMES = {"__MACOSX"}
ENTRYPOINT_FILENAMES = {"app.py", "wsgi.py", "run.py"}


class UploadError(Exception):
    pass


def _is_within_directory(directory: str, target: str) -> bool:
    abs_directory = os.path.abspath(directory)
    abs_target = os.path.abspath(target)
    return os.path.commonpath([abs_directory]) == os.path.commonpath([abs_directory, abs_target])


def _remove_upload_junk(dest_dir: str) -> None:
    for root, dirs, files in os.walk(dest_dir, topdown=False):
        for filename in files:
            if filename in JUNK_FILE_NAMES or filename.startswith("._"):
                os.remove(os.path.join(root, filename))
        for dirname in dirs:
            path = os.path.join(root, dirname)
            if dirname in JUNK_DIR_NAMES:
                shutil.rmtree(path)


def _has_supported_entrypoint(directory: str) -> bool:
    return any(os.path.isfile(os.path.join(directory, filename)) for filename in ENTRYPOINT_FILENAMES)


def _flatten_single_root_directory(dest_dir: str) -> None:
    if _has_supported_entrypoint(dest_dir):
        return

    entries = os.listdir(dest_dir)
    directories = [entry for entry in entries if os.path.isdir(os.path.join(dest_dir, entry))]
    if len(entries) != 1 or len(directories) != 1:
        return

    inner = os.path.join(dest_dir, directories[0])
    for name in os.listdir(inner):
        shutil.move(os.path.join(inner, name), os.path.join(dest_dir, name))
    shutil.rmtree(inner)


def _validate_supported_entrypoint(dest_dir: str) -> None:
    if _has_supported_entrypoint(dest_dir):
        return
    supported = ", ".join(sorted(ENTRYPOINT_FILENAMES))
    raise UploadError(
        "No se encontro un archivo de entrada Flask en la raiz del proyecto. "
        f"Incluye uno de estos archivos en el .zip: {supported}."
    )


def extract_zip_safely(file_storage, dest_dir: str) -> None:
    """Extrae un zip subido por el usuario validando cada entrada contra path
    traversal (zip-slip) y limitando el numero de archivos y el tamano total
    descomprimido (mitiga zip-bombs)."""
    if os.path.isdir(dest_dir):
        shutil.rmtree(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(file_storage) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_FILES:
                raise UploadError(f"El archivo zip tiene demasiados elementos. Limite actual: {MAX_FILES}.")

            total_size = 0
            for info in infos:
                total_size += info.file_size
                if total_size > MAX_UNCOMPRESSED_SIZE:
                    limit_mb = MAX_UNCOMPRESSED_SIZE // (1024 * 1024)
                    raise UploadError(f"El proyecto descomprimido supera el limite de tamano permitido ({limit_mb} MB).")

                target_path = os.path.join(dest_dir, info.filename)
                if not _is_within_directory(dest_dir, target_path):
                    raise UploadError("El zip contiene rutas invalidas (path traversal).")

            zf.extractall(dest_dir)
    except zipfile.BadZipFile as exc:
        raise UploadError("El archivo no es un zip valido.") from exc

    _remove_upload_junk(dest_dir)
    _flatten_single_root_directory(dest_dir)
    _validate_supported_entrypoint(dest_dir)
