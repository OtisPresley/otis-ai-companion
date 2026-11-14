"""Otis AI Companion: HA Core Log Monitor & GitHub Issue Tracking Engine.

Monitors Home Assistant Core logs and system_log records for actionable errors,
distinguishing self-healing transient/config anomalies from genuine integration bugs,
sanitizing diagnostic traces, and tracking community GitHub issues in the Proactive Feed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .github_client import (
    DEFAULT_GITHUB_REPO,
    clean_repo_slug,
    get_github_issue,
)

_LOGGER = logging.getLogger(__name__)

# Sensitive data sanitization regex patterns
RE_IPV4 = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b"
)
RE_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
RE_BEARER = re.compile(r"(?i)(?:bearer\s+|token[\s=:]+)[a-zA-Z0-9_\-\.]{16,}")
RE_PASSWORD = re.compile(r"(?i)(password|secret|api_key|token|access_token)[\s=:]+['\"]?[^'\">\s,;]+['\"]?")
RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")
RE_USER_PATH = re.compile(r"/(?:home|Users)/[a-zA-Z0-9_\-]+/")

# System, script, automation, and helper domains that execute user templates or configurations
# and are NEVER third-party integration code bugs reportable to GitHub.
NON_INTEGRATION_DOMAINS = {
    "automation",
    "script",
    "scene",
    "template",
    "group",
    "zone",
    "homeassistant",
    "system_log",
    "logger",
    "concurrent",
    "asyncio",
    "threading",
    "multiprocessing",
    "urllib3",
    "requests",
    "aiohttp",
    "httpx",
    "httpcore",
    "websockets",
    "zeroconf",
    "scapy",
    "pip",
    "root",
}

# Transient self-healing keywords (network drops, device sleep/offline, handshake retries)
SELF_HEALING_KEYWORDS = (
    "unable to communicate with the device",
    "responded with 403 to handshake",
    "connection reset by peer",
    "timeouterror",
    "cannot connect to host",
    "clientconnectorerror",
    "retrying in",
    "waiting for device to come online",
    "temporary failure in name resolution",
    "connection refused",
    "failed to connect",
    "server disconnected",
    "network is unreachable",
    "handshake failed",
    "adb connection",
    "re-establishing attempt",
    "failed to execute an adb command",
    "device is offline",
    "device offline",
    "device unreachable",
    "device did not respond",
    "could not connect",
    "connection was closed",
    "connection closed",
    "broken pipe",
    "host is down",
    "no route to host",
    "temporarily unavailable",
    "poll failed",
    "failed to send http request",
    "failed to access api",
    "ssl: unexpected_record",
    "remote end closed connection",
    "timeout while accessing",
    "unable to fetch data",
    "timeout while",
    "timeout fetching",
    "error fetching",
    "invalid response received from",
    "invalid response from",
    "printer",
    "updatefailed",
    "update failed",
    "communication error",
    "client error",
    "service unavailable",
    "bad gateway",
    "gateway time-out",
    "gateway timeout",
    "failed to update media",
    "failed to load img",
)

TRANSIENT_EXCEPTIONS = (
    "connectionreseterror",
    "connectionrefusederror",
    "connectionerror",
    "timeouterror",
    "clientconnectorerror",
    "brokenpipeerror",
    "oserror",
    "clientpayloaderror",
    "serverdisconnectederror",
    "clientoserror",
    "handshakeerror",
)

# Exception patterns that represent actionable integration bugs
INTEGRATION_BUG_KEYWORDS = (
    "traceback (most recent call last):",
    "attributeerror",
    "typeerror",
    "keyerror",
    "indexerror",
    "zerodivisionerror",
    "unboundlocalerror",
    "notimplementederror",
    "syntaxerror",
    "setup failed for custom integration",
    "error setting up platform",
    "unexpected error",
)


def sanitize_log_data(text: str) -> str:
    """Sanitize sensitive host data, local IPs, credentials, emails, and usernames from text."""
    if not text:
        return ""
    sanitized = str(text)
    sanitized = RE_BEARER.sub("Bearer [REDACTED_TOKEN]", sanitized)
    sanitized = RE_PASSWORD.sub(r"\1=[REDACTED]", sanitized)
    sanitized = RE_EMAIL.sub("[REDACTED_EMAIL]", sanitized)
    sanitized = RE_IPV4.sub("[LOCAL_IP]", sanitized)
    sanitized = RE_MAC.sub("[LOCAL_MAC]", sanitized)
    sanitized = RE_USER_PATH.sub("/config/", sanitized)
    return sanitized


class LogMonitor:
    """Audits Home Assistant Core logs, detects bugs, and tracks GitHub issues."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the Log Monitor."""
        self.hass = hass
        self._store = Store(hass, 1, "otis_ai_tracked_issues")
        self._tracked_issues: dict[str, dict[str, Any]] = {}
        self._loaded: bool = False
        self._manifest_cache: dict[str, str] = {}
        self._dismissed_error_ids: set[str] = set()

    async def async_load(self) -> None:
        """Load tracked issues and dismissed error states from storage."""
        if self._loaded:
            return
        try:
            data = await self._store.async_load()
            if isinstance(data, dict):
                issues = data.get("issues", {})
                if isinstance(issues, dict):
                    self._tracked_issues = issues
                elif isinstance(issues, list):
                    self._tracked_issues = {
                        str(item.get("id") or item.get("number")): item for item in issues if isinstance(item, dict)
                    }
                self._dismissed_error_ids = set(data.get("dismissed_errors", []))
        except Exception as err:
            _LOGGER.debug("Could not load tracked issues store: %s", err)
        finally:
            self._loaded = True

    async def async_save(self) -> None:
        """Persist tracked issues and dismissed error states to storage."""
        try:
            await self._store.async_save({
                "issues": self._tracked_issues,
                "dismissed_errors": list(self._dismissed_error_ids),
                "updated_at": time.time(),
            })
        except Exception as err:
            _LOGGER.debug("Could not save tracked issues store: %s", err)

    def _resolve_target_repo_sync(self, domain: str) -> str:
        """Resolve the GitHub repository slug for an integration domain from its manifest."""
        if not domain:
            return DEFAULT_GITHUB_REPO
        if domain in self._manifest_cache:
            return self._manifest_cache[domain]

        # 1. Custom components check
        custom_manifest_path = self.hass.config.path("custom_components", domain, "manifest.json")
        if os.path.isfile(custom_manifest_path):
            try:
                with open(custom_manifest_path, encoding="utf-8") as f:
                    m = json.load(f)
                    tracker = m.get("issue_tracker") or m.get("documentation") or ""
                    if "github.com/" in tracker:
                        repo = clean_repo_slug(tracker)
                        self._manifest_cache[domain] = repo
                        return repo
            except Exception:
                pass

        # 2. Domain heuristics
        if domain == "otis_ai":
            repo = "OtisPresley/otis-ai-companion"
        elif "snmp_switch" in domain:
            repo = "OtisPresley/snmp-switch-manager"
        elif "snmp_net" in domain:
            repo = "OtisPresley/snmp-network-manager"
        elif "control4" in domain:
            repo = "OtisPresley/control4-mediaplayer-card"
        else:
            repo = DEFAULT_GITHUB_REPO

        self._manifest_cache[domain] = repo
        return repo

    async def async_resolve_target_repo(self, domain: str) -> str:
        """Resolve the GitHub repository slug for an integration domain."""
        if hasattr(self.hass, "async_add_executor_job"):
            res = self.hass.async_add_executor_job(self._resolve_target_repo_sync, domain)
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                return await res
            elif isinstance(res, str):
                return res
        return self._resolve_target_repo_sync(domain)

    def get_system_log_records(self) -> list[dict[str, Any]]:
        """Retrieve deduplicated log records from Home Assistant's system_log handler."""
        handler = self.hass.data.get("system_log")
        if handler and hasattr(handler, "records") and hasattr(handler.records, "to_list"):
            try:
                return handler.records.to_list()
            except Exception as err:
                _LOGGER.debug("Error querying system_log records: %s", err)
        return []

    @staticmethod
    def _parse_log_record(r: Any) -> tuple[str, str, str, str, int, float, Any]:
        """Extract normalized fields from a dict or LogEntry system_log record."""
        is_dict = isinstance(r, dict)
        getter = r.get if is_dict else lambda k, d=None: getattr(r, k, d)
        name = str(getter("name", "") or "")
        msg_list = getter("message", []) or []
        level = str(getter("level", "ERROR") or "ERROR").upper()
        exc = str(getter("exception", "") or "")
        count = int(getter("count", 1) or 1)
        timestamp = float(getter("timestamp", None) or time.time())
        source = getter("source", []) or []
        msg_text = (
            "\n".join(str(m) for m in msg_list)
            if isinstance(msg_list, (list, tuple))
            else str(msg_list)
        )
        return name, msg_text, level, exc, count, timestamp, source

    async def async_audit_logs(self) -> dict[str, list[dict[str, Any]]]:
        """Audit current system log entries, separating bugs from self-healing/transient notices."""
        await self.async_load()
        records = self.get_system_log_records()

        integration_bugs: list[dict[str, Any]] = []
        self_healing: list[dict[str, Any]] = []

        ha_version = getattr(self.hass.config, "version", "2026.x")

        for r in records:
            name, msg_text, level, exc, count, timestamp, source = self._parse_log_record(r)

            combined_raw = f"{name} {msg_text} {exc}".lower()

            # Extract domain
            domain = ""
            from_traceback = False
            if name.startswith("custom_components."):
                parts = name.split(".")
                domain = parts[1] if len(parts) > 1 else "custom"
            elif name.startswith("homeassistant.components."):
                parts = name.split(".")
                domain = parts[2] if len(parts) > 2 else "core"
            else:
                tb_match = re.search(
                    r"(?:custom_components|homeassistant[/\\.]components)[/\\.]([a-zA-Z0-9_]+)",
                    f"{msg_text}\n{exc}\n{source}",
                )
                if tb_match:
                    domain = tb_match.group(1)
                    from_traceback = True
                else:
                    domain = name.split(".")[0]

            friendly_name = domain.replace("_", " ").title()
            target_repo = await self.async_resolve_target_repo(domain)

            # Unique deterministic ID for this error signature
            sig_text = f"{domain}:{msg_text[:120]}:{source}"
            error_id = hashlib.sha256(sig_text.encode("utf-8")).hexdigest()[:12]

            # 1. Skip non-integration / user config domains & standard library loggers
            if not (name.startswith("custom_components.") or name.startswith("homeassistant.components.") or from_traceback):
                continue

            if (
                domain in NON_INTEGRATION_DOMAINS
                or name.startswith("frontend.")
                or any(d in name for d in ("components.automation", "components.script", "helpers.script", "helpers.template"))
            ):
                continue

            # 2. Classify self-healing / transient connectivity drops & device offline states
            is_transient = any(k in combined_raw for k in SELF_HEALING_KEYWORDS) or any(k in combined_raw for k in TRANSIENT_EXCEPTIONS)
            has_code_bug_exc = any(err in exc for err in ("AttributeError", "TypeError", "KeyError", "IndexError", "ZeroDivisionError", "UnboundLocalError", "AssertionError", "NameError", "SyntaxError", "NotImplementedError"))
            if is_transient and not has_code_bug_exc:
                self_healing.append({
                    "id": error_id,
                    "domain": domain,
                    "integration_name": friendly_name,
                    "logger": name,
                    "level": level,
                    "count": count,
                    "timestamp": timestamp,
                    "message": sanitize_log_data(msg_text[:200]),
                })
                continue

            # 3. Classify integration bug: MUST have an actual code bug exception or setup failure
            is_bug = has_code_bug_exc or any(k in combined_raw for k in ("setup failed for custom integration", "error setting up platform"))
            if not is_bug:
                continue

            sanitized_msg = sanitize_log_data(msg_text)
            sanitized_exc = sanitize_log_data(exc)
            short_err = sanitized_msg.splitlines()[0] if sanitized_msg else "Unhandled Exception"
            if len(short_err) > 90:
                short_err = short_err[:87] + "..."

            suggested_title = f"[Bug Report] {domain}: {short_err}"
            sanitized_body = (
                f"### Issue Description\n"
                f"An unhandled error occurred in integration `{domain}` running on Home Assistant {ha_version}.\n\n"
                f"**Logger:** `{name}`\n"
                f"**Occurrences:** {count} times\n"
                f"**Source:** `{source}`\n\n"
                f"### Error Log / Stack Trace\n"
                f"```text\n{sanitized_msg}\n"
                f"{sanitized_exc}\n```\n\n"
                f"### Environment\n"
                f"- Home Assistant Version: {ha_version}\n"
                f"- Architecture: {self.hass.config.as_dict().get('architecture', 'Linux') if callable(getattr(self.hass.config, 'as_dict', None)) else 'Linux'}\n"
                f"- Reported via: Otis AI Companion Auto-Diagnostics\n"
            )

            integration_bugs.append({
                "id": error_id,
                "domain": domain,
                "integration_name": friendly_name,
                "logger": name,
                "level": level,
                "count": count,
                "timestamp": timestamp,
                "short_error": short_err,
                "suggested_title": suggested_title,
                "sanitized_body": sanitized_body,
                "target_repo": target_repo,
                "source": source,
            })

        return {
            "integration_bugs": integration_bugs,
            "self_healing": self_healing,
        }

    async def async_track_issue(
        self,
        repo: str,
        issue_number: int,
        title: str,
        html_url: str,
        error_id: str | None = None,
        summary: str = "",
    ) -> dict[str, Any]:
        """Add a newly created GitHub issue to persistent proactive tracking."""
        await self.async_load()
        track_id = f"{clean_repo_slug(repo)}#{issue_number}"
        issue_entry = {
            "id": track_id,
            "repo": clean_repo_slug(repo),
            "number": issue_number,
            "title": title.strip(),
            "html_url": html_url.strip(),
            "state": "open",
            "created_at": time.time(),
            "summary": summary.strip() or title.strip(),
            "dismissed": False,
        }
        self._tracked_issues[track_id] = issue_entry
        if error_id:
            self._dismissed_error_ids.add(error_id)
        await self.async_save()
        _LOGGER.info("Otis AI: Now tracking GitHub issue %s in Proactive Feed", track_id)
        return issue_entry

    async def async_dismiss_issue(self, track_id: str) -> bool:
        """Dismiss a tracked issue from the active Proactive Feed."""
        await self.async_load()
        if track_id in self._tracked_issues:
            self._tracked_issues[track_id]["dismissed"] = True
            await self.async_save()
            return True
        return False

    async def async_dismiss_error(self, error_id: str) -> bool:
        """Dismiss a detected log error from active suggestion cards."""
        await self.async_load()
        self._dismissed_error_ids.add(error_id)
        await self.async_save()
        return True

    async def async_refresh_tracked_issues(self) -> dict[str, dict[str, Any]]:
        """Poll GitHub API to update status (open/closed) of all active tracked issues."""
        await self.async_load()
        for track_id, issue in list(self._tracked_issues.items()):
            if issue.get("dismissed"):
                continue
            repo = issue.get("repo")
            num = issue.get("number")
            if not repo or not num:
                continue
            try:
                live = await get_github_issue(repo, int(num))
                if live and "state" in live:
                    issue["state"] = live["state"]
                    issue["title"] = live.get("title", issue["title"])
            except Exception as err:
                _LOGGER.debug("Could not refresh issue %s: %s", track_id, err)

        await self.async_save()
        return self._tracked_issues

    async def async_get_proactive_cards(self) -> list[dict[str, Any]]:
        """Generate high-priority Proactive Feed cards for tracked issues and actionable bugs."""
        await self.async_load()
        cards: list[dict[str, Any]] = []

        # 1. Active Tracked GitHub Issues
        for track_id, issue in self._tracked_issues.items():
            if issue.get("dismissed"):
                continue
            st = str(issue.get("state", "open")).lower()
            state_badge = "🟢 OPEN" if st == "open" else "🟣 CLOSED"
            num = issue.get("number")
            title = issue.get("title")
            url = issue.get("html_url")
            repo = issue.get("repo")

            cards.append({
                "id": f"tracked_gh_{track_id}",
                "title": f"🐙 GitHub Issue #{num}: {title}",
                "category": "system",
                "priority": "medium",
                "icon": "mdi:github",
                "description": f"Status: {state_badge} • Target: `{repo}`\nOtis AI is actively tracking this issue on GitHub.",
                "action_type": "tracked_github_issue",
                "action_payload": {
                    "track_id": track_id,
                    "issue_number": num,
                    "issue_url": url,
                    "repo": repo,
                    "state": st,
                    "title": title,
                },
            })

        # 2. Actionable Integration Bugs
        audit = await self.async_audit_logs()
        for bug in audit.get("integration_bugs", [])[:3]:
            err_id = bug["id"]
            if err_id in self._dismissed_error_ids:
                continue
            # Check if this error already matches an active tracked issue
            if any(isinstance(it, dict) and bug["domain"] in str(it.get("title", "")).lower() for it in self._tracked_issues.values()):
                continue

            cards.append({
                "id": f"bug_report_{err_id}",
                "title": f"🐛 Integration Bug: {bug['integration_name']}",
                "category": "system",
                "priority": "high",
                "icon": "mdi:bug",
                "description": (
                    f"Detected unhandled error in `{bug['domain']}` ({bug['short_error']}). "
                    f"Reported {bug['count']} times. Otis AI can submit a sanitized report directly to GitHub."
                ),
                "action_type": "github_report_issue",
                "action_payload": {
                    "error_id": err_id,
                    "domain": bug["domain"],
                    "integration_name": bug["integration_name"],
                    "logger": bug["logger"],
                    "count": bug["count"],
                    "suggested_title": bug["suggested_title"],
                    "sanitized_body": bug["sanitized_body"],
                    "target_repo": bug["target_repo"],
                },
            })

        # 3. Self-healing notice (if multiple transient drops detected)
        for notice in audit.get("self_healing", [])[:2]:
            n_id = notice["id"]
            if n_id in self._dismissed_error_ids:
                continue
            cards.append({
                "id": f"self_healing_{n_id}",
                "title": f"⏳ Self-Healing: {notice['integration_name']}",
                "category": "system",
                "priority": "low",
                "icon": "mdi:progress-wrench",
                "description": (
                    f"Temporary network or handshake drop ({notice['message']}). "
                    f"Home Assistant is automatically reconnecting. No bug report needed."
                ),
                "action_type": "dismiss_self_healing_alert",
                "action_payload": {
                    "error_id": n_id,
                },
            })

        return cards

    async def async_summarize_logs_for_copilot(self) -> str:
        """Build a concise, sanitized Markdown summary of current HA system logs for Assist Co-Pilot."""
        audit = await self.async_audit_logs()
        bugs = audit.get("integration_bugs", [])
        self_healing = audit.get("self_healing", [])
        records = self.get_system_log_records()

        bug_loggers = {(b.get("logger", ""), b.get("short_error", "")[:40]) for b in bugs}
        other_issues: list[dict[str, Any]] = []
        seen_other: set[str] = set()

        for r in records:
            name, msg_text, level, _exc, count, _ts, _src = self._parse_log_record(r)
            name = name or "homeassistant"
            if level not in ("CRITICAL", "ERROR", "WARNING"):
                continue
            sanitized = sanitize_log_data(msg_text).splitlines()[0] if msg_text else ""
            if len(sanitized) > 140:
                sanitized = sanitized[:137] + "..."
            if (name, sanitized[:40]) in bug_loggers:
                continue
            dedup_key = f"{level}:{name}:{sanitized[:60]}"
            if dedup_key in seen_other:
                continue
            seen_other.add(dedup_key)
            other_issues.append({
                "level": level,
                "logger": name,
                "count": count,
                "message": sanitized or "(no message)",
            })

        # Sort other issues: CRITICAL -> ERROR -> WARNING, then highest count
        sev_rank = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2}
        other_issues.sort(key=lambda x: (sev_rank.get(x["level"], 3), -x["count"]))

        if not bugs and not other_issues and not self_healing:
            return (
                "📋 **Home Assistant System Log Audit**\n\n"
                "I inspected your live Home Assistant `system_log` buffer (`"
                f"{len(records)}` total record(s)) and found **no active integration bugs, errors, or warnings** that need to be addressed right now."
            )

        lines: list[str] = [
            f"📋 **Home Assistant System Log Audit** ({len(records)} active `system_log` record(s))\n"
        ]
        if bugs:
            lines.append(f"**1. Integration Bugs / Unhandled Exceptions ({len(bugs)}):**")
            for b in bugs[:6]:
                lines.append(
                    f"• `{b['domain']}` ({b['level']}, {b['count']}x): {b['short_error']} — *logger:* `{b['logger']}`"
                )
            lines.append("")

        if other_issues:
            shown = other_issues[:8]
            lines.append(f"**{'2' if bugs else '1'}. Errors & Warnings ({len(other_issues)} unique):**")
            for item in shown:
                lines.append(
                    f"• **[{item['level']}]** `{item['logger']}` ({item['count']}x): {item['message']}"
                )
            if len(other_issues) > len(shown):
                lines.append(f"• *...and {len(other_issues) - len(shown)} more warning/error entries.*")
            lines.append("")

        if self_healing:
            domains = sorted({n.get("integration_name", n.get("domain", "unknown")) for n in self_healing})
            lines.append(
                f"**Transient / Self-Healing Notices ({len(self_healing)}):** "
                f"Temporary timeouts/reconnects in {', '.join(domains[:5])} — usually resolve automatically."
            )
            lines.append("")

        lines.append(
            "Ask me about any specific logger/integration above to troubleshoot it, or open **Proactive Feed** to file a sanitized GitHub bug report."
        )
        return "\n".join(lines)
