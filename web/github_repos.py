import os
import json
import time
import urllib.request
import urllib.error
import logging

logger = logging.getLogger("agent.github_repos")

_cache: dict = {"repos": [], "fetched_at": 0.0}
_CACHE_TTL = 300  # 5 minutes


def _get_pat() -> str:
    return os.getenv("GITHUB_PAT", "")


def fetch_github_repos() -> list[dict]:
    """
    Fetch all repos accessible via the GITHUB_PAT environment variable.
    Results are cached for 5 minutes to avoid hammering the API.
    Returns a list of dicts: {name, full_name, url, owner, default_branch}.
    Returns [] if PAT is missing or the API call fails.
    """
    now = time.time()
    if _cache["repos"] and now - _cache["fetched_at"] < _CACHE_TTL:
        return _cache["repos"]

    pat = _get_pat()
    if not pat:
        logger.warning("GITHUB_PAT not set — cannot discover repos")
        return []

    repos = []
    page = 1
    while True:
        api_url = (
            f"https://api.github.com/user/repos"
            f"?per_page=100&page={page}&sort=updated&affiliation=owner,collaborator,organization_member"
        )
        req = urllib.request.Request(
            api_url,
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "red-eye-agent",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.warning(f"GitHub API HTTP error {e.code}: {e.reason}")
            break
        except urllib.error.URLError as e:
            logger.warning(f"GitHub API connection error: {e.reason}")
            break

        if not data:
            break

        for r in data:
            repos.append(
                {
                    "name": r["name"],
                    "full_name": r["full_name"],
                    "url": r["clone_url"],
                    "owner": r["owner"]["login"],
                    "default_branch": r.get("default_branch", "main"),
                }
            )

        if len(data) < 100:
            break
        page += 1

    _cache["repos"] = repos
    _cache["fetched_at"] = now
    logger.info(f"Fetched {len(repos)} repos from GitHub API")
    return repos


def merge_with_config(config_repos: list[dict]) -> list[str]:
    """
    Merge GitHub-discovered repos with repos already in config.yaml.
    Config repos take precedence (they already have custom settings).
    Returns a sorted list of unique repo names.
    """
    config_names = {r["name"] for r in config_repos}
    github_repos = fetch_github_repos()
    all_names = set(config_names)
    for r in github_repos:
        all_names.add(r["name"])
    return sorted(all_names)


def get_repo_defaults(repo_name: str) -> dict | None:
    """
    Return default config entry for a GitHub-discovered repo, or None
    if the repo isn't found in the GitHub API response.
    """
    for r in _cache.get("repos", []):
        if r["name"] == repo_name:
            return {
                "name": r["name"],
                "url": r["url"],
                "branch_prefix": "agent/",
                "default_branch": r["default_branch"],
                "test_command": None,
            }
    return None
