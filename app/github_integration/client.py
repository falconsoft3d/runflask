import requests

GITHUB_API = "https://api.github.com"
OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"

REQUEST_TIMEOUT = 15


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "repo",
        "state": state,
        "allow_signup": "true",
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return f"{OAUTH_AUTHORIZE_URL}?{query}"


def exchange_code_for_token(client_id: str, client_secret: str, code: str, redirect_uri: str) -> str:
    resp = requests.post(
        OAUTH_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Error de OAuth de GitHub: {data.get('error_description', data['error'])}")
    return data["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def get_authenticated_user(token: str) -> dict:
    resp = requests.get(f"{GITHUB_API}/user", headers=_headers(token), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def list_user_repos(token: str) -> list:
    repos = []
    page = 1
    while True:
        resp = requests.get(
            f"{GITHUB_API}/user/repos",
            headers=_headers(token),
            params={"per_page": 100, "page": page, "sort": "updated"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def create_webhook(token: str, repo_full_name: str, webhook_url: str, secret: str) -> dict:
    resp = requests.post(
        f"{GITHUB_API}/repos/{repo_full_name}/hooks",
        headers=_headers(token),
        json={
            "name": "web",
            "active": True,
            "events": ["push"],
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": secret,
                "insecure_ssl": "0",
            },
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def delete_webhook(token: str, repo_full_name: str, hook_id: str) -> None:
    requests.delete(
        f"{GITHUB_API}/repos/{repo_full_name}/hooks/{hook_id}",
        headers=_headers(token),
        timeout=REQUEST_TIMEOUT,
    )
