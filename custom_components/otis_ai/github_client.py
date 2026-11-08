"""Otis AI Companion: GitHub Device Flow & Issue Tracker API Client.

Enables seamless non-admin & admin GitHub Device Flow authentication
and sanitized issue submission directly from Home Assistant.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Verified GitHub OAuth Client ID for Otis integrations device flow
GITHUB_CLIENT_ID = "Ov23liTlBABZlhQen9QI"
DEFAULT_GITHUB_REPO = "OtisPresley/otis-ai-companion"


async def request_device_code(client_id: str = GITHUB_CLIENT_ID) -> dict[str, Any] | None:
    """Request a device code from GitHub OAuth Device Flow."""
    url = "https://github.com/login/device/code"
    headers = {"Accept": "application/json"}
    payload = {
        "client_id": client_id,
        "scope": "public_repo",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, data=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                _LOGGER.error("Failed to request GitHub device code: HTTP %s", response.status)
    except Exception as err:
        _LOGGER.error("Error requesting GitHub device code: %s", err)
    return None


async def check_device_token(
    client_id: str = GITHUB_CLIENT_ID,
    device_code: str = "",
) -> dict[str, Any]:
    """Check if the user has completed device flow authorization (single non-blocking poll)."""
    if not device_code:
        return {"status": "error", "error": "Missing device code"}

    url = "https://github.com/login/oauth/access_token"
    headers = {"Accept": "application/json"}
    payload = {
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, data=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if "access_token" in data:
                        return {
                            "status": "success",
                            "token": data["access_token"],
                            "token_type": data.get("token_type", "bearer"),
                        }
                    err = data.get("error")
                    if err == "authorization_pending":
                        return {"status": "pending", "message": "Authorization pending user approval"}
                    if err == "slow_down":
                        interval = data.get("interval", 5)
                        return {"status": "slow_down", "interval": interval}
                    if err == "expired_token":
                        return {"status": "expired", "error": "Device code has expired. Please request a new code."}
                    return {"status": "error", "error": data.get("error_description") or err or "Authorization failed"}
                return {"status": "error", "error": f"HTTP {response.status}"}
    except Exception as err:
        _LOGGER.error("Error checking GitHub device token: %s", err)
        return {"status": "error", "error": str(err)}


async def poll_for_token(
    client_id: str = GITHUB_CLIENT_ID,
    device_code: str = "",
    interval: int = 5,
    timeout: int = 180,
) -> str | None:
    """Poll GitHub for the access token until authorized or expired."""
    start_time = asyncio.get_event_loop().time()
    curr_interval = max(2, interval)

    while (asyncio.get_event_loop().time() - start_time) < timeout:
        res = await check_device_token(client_id=client_id, device_code=device_code)
        st = res.get("status")
        if st == "success":
            return res.get("token")
        if st == "expired" or st == "error":
            _LOGGER.warning("GitHub device flow failed: %s", res.get("error"))
            return None
        if st == "slow_down":
            curr_interval = res.get("interval", curr_interval + 5)

        await asyncio.sleep(curr_interval)

    _LOGGER.warning("GitHub device flow polling timed out after %ds", timeout)
    return None


def clean_repo_slug(raw_repo: str) -> str:
    """Sanitize and validate a GitHub repository slug (e.g. 'owner/repo')."""
    cleaned = str(raw_repo or "").strip()
    cleaned = re.sub(r"^https?://github\.com/", "", cleaned)
    cleaned = cleaned.rstrip("/").removesuffix(".git").removesuffix("/issues")
    match = re.match(r"^([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+)$", cleaned)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return DEFAULT_GITHUB_REPO


async def create_github_issue(
    token: str,
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new issue on the specified GitHub repository."""
    repo_slug = clean_repo_slug(repo)
    url = f"https://api.github.com/repos/{repo_slug}/issues"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload: dict[str, Any] = {
        "title": title.strip()[:250],
        "body": body.strip(),
    }
    if labels:
        payload["labels"] = labels

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 201:
                    data = await response.json()
                    return {
                        "success": True,
                        "number": data.get("number"),
                        "html_url": data.get("html_url"),
                        "state": data.get("state", "open"),
                        "title": data.get("title", title),
                        "repo": repo_slug,
                    }
                # If 422 Unprocessable (e.g. custom label does not exist on third-party repo), retry without labels
                if response.status == 422 and "labels" in payload:
                    del payload["labels"]
                    async with session.post(url, headers=headers, json=payload) as retry_resp:
                        if retry_resp.status == 201:
                            data = await retry_resp.json()
                            return {
                                "success": True,
                                "number": data.get("number"),
                                "html_url": data.get("html_url"),
                                "state": data.get("state", "open"),
                                "title": data.get("title", title),
                                "repo": repo_slug,
                            }
                resp_text = await response.text()
                _LOGGER.error("Failed to create GitHub issue on %s (HTTP %s): %s", repo_slug, response.status, resp_text)
                return {"success": False, "error": f"GitHub returned HTTP {response.status}: {resp_text}"}
    except Exception as err:
        _LOGGER.error("Exception creating GitHub issue on %s: %s", repo_slug, err)
        return {"success": False, "error": str(err)}


async def get_github_issue(
    repo: str,
    issue_number: int,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Fetch live metadata (state, comments, updated_at) for a tracked issue."""
    repo_slug = clean_repo_slug(repo)
    url = f"https://api.github.com/repos/{repo_slug}/issues/{issue_number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "number": data.get("number"),
                        "title": data.get("title"),
                        "state": data.get("state", "open"),
                        "html_url": data.get("html_url"),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "closed_at": data.get("closed_at"),
                        "comments": data.get("comments", 0),
                        "repo": repo_slug,
                    }
                _LOGGER.debug("Could not fetch issue %s#%s: HTTP %s", repo_slug, issue_number, response.status)
    except Exception as err:
        _LOGGER.debug("Error fetching GitHub issue %s#%s: %s", repo_slug, issue_number, err)
    return None

