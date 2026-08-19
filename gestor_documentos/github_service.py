import base64
import json
from urllib import error, parse, request

from django.conf import settings

from .models import SistemaConfiguracion


class GitHubSyncError(Exception):
    pass


def github_configured():
    owner, repo = _get_github_owner_repo()
    return bool(owner and repo and _get_github_token())


def _get_github_token():
    try:
        configured_token = SistemaConfiguracion.get_solo().github_token.strip()
    except Exception:
        configured_token = ""
    return configured_token or settings.GITHUB_TOKEN


def _get_github_owner_repo():
    try:
        config = SistemaConfiguracion.get_solo()
        configured_owner = config.github_owner.strip()
        configured_repo = config.github_repo.strip()
    except Exception:
        configured_owner = ""
        configured_repo = ""
    return configured_owner or settings.GITHUB_OWNER, configured_repo or settings.GITHUB_REPO


def _build_headers():
    return {
        "Authorization": f"Bearer {_get_github_token()}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "GestorDocumentos",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _build_url(path):
    owner_value, repo_value = _get_github_owner_repo()
    owner = parse.quote(owner_value, safe="")
    repo = parse.quote(repo_value, safe="")
    encoded_path = parse.quote(path.strip("/"), safe="/")
    return f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}"


def _request_json(method, path, payload):
    if not github_configured():
        raise GitHubSyncError("GitHub no esta configurado en el servidor.")

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        _build_url(path),
        data=data,
        headers=_build_headers(),
        method=method,
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise GitHubSyncError(f"GitHub respondio con error al sincronizar: {detail}") from exc
    except error.URLError as exc:
        raise GitHubSyncError("No fue posible conectar con GitHub.") from exc


def _get_json(path):
    if not github_configured():
        raise GitHubSyncError("GitHub no esta configurado en el servidor.")

    req = request.Request(
        _build_url(path),
        headers=_build_headers(),
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        if exc.code == 404:
            return None
        detail = exc.read().decode("utf-8", errors="ignore")
        raise GitHubSyncError(f"GitHub respondio con error al consultar: {detail}") from exc
    except error.URLError as exc:
        raise GitHubSyncError("No fue posible conectar con GitHub.") from exc


def ensure_directory(path, marker_text):
    normalized = path.strip("/")
    if not normalized:
        raise GitHubSyncError("La ruta a crear en GitHub es invalida.")

    marker_path = f"{normalized}/.gitkeep"
    payload = {
        "message": f"Crear carpeta {normalized}",
        "content": base64.b64encode(marker_text.encode("utf-8")).decode("utf-8"),
    }
    current_file = _get_json(marker_path)
    if current_file and "sha" in current_file:
        payload["sha"] = current_file["sha"]
        payload["message"] = f"Actualizar carpeta {normalized}"

    _request_json("PUT", marker_path, payload)


def upsert_text_file(path, text_content, commit_message):
    normalized = path.strip("/")
    if not normalized:
        raise GitHubSyncError("La ruta del archivo markdown es invalida.")

    payload = {
        "message": commit_message,
        "content": base64.b64encode(text_content.encode("utf-8")).decode("utf-8"),
    }
    current_file = _get_json(normalized)
    if current_file and "sha" in current_file:
        payload["sha"] = current_file["sha"]

    _request_json("PUT", normalized, payload)


def delete_text_file(path, commit_message):
    normalized = path.strip("/")
    if not normalized:
        raise GitHubSyncError("La ruta del archivo markdown es invalida.")

    current_file = _get_json(normalized)
    if not current_file:
        return

    payload = {
        "message": commit_message,
        "sha": current_file["sha"],
    }
    _request_json("DELETE", normalized, payload)
