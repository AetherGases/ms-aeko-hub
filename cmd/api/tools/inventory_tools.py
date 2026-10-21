"""Expose typed inventory upload and analysis tools backed by domain services."""

import ipaddress
import logging
import os
import socket
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from langchain_core.tools import Tool, create_schema_from_function
from pydantic import BaseModel

from cmd.api.acl.open_ai.identity import (
    current_id_external_company,
    current_id_external_user,
)
from cmd.api.integrations.cloudinary_api import CloudinaryError, get_upload_signature
from cmd.api.integrations.cloudinary_upload import upload_signed_file
from cmd.api.integrations.inventory_api import InventoryError
from cmd.api.tools.constants import (
    ANALYZE_INVENTORY_DESCRIPTION,
    GET_INVENTORY_ANALYSIS_DESCRIPTION,
)
from cmd.api.tools.mongo_tools import _positive_int, _required_text
from upload_ticket.entity import STATE_UPLOADED


logger = logging.getLogger(__name__)

_tickets_service = None
_create_inventory = None
_plans_service = None
_inventory_response_keys = ("id", "name", "type", "status", "createdAt")


class ChatGPTInventoryFile(BaseModel):
    """Host file object ChatGPT attaches to analyze_inventory."""

    download_url: str
    file_id: str
    mime_type: str | None = None
    file_name: str | None = None


def configure(*, tickets=None, create_inventory=None, plans=None) -> None:
    """Bind upload tickets, inventory creation, and improvement plans."""

    global _tickets_service, _create_inventory, _plans_service
    _tickets_service = tickets
    _create_inventory = create_inventory
    _plans_service = plans


def _tickets():
    """Return the configured upload-ticket service."""

    if _tickets_service is None:
        raise RuntimeError("Upload ticket service is not configured.")
    return _tickets_service


def _inventory_creator() -> Callable[[str, str, str], dict]:
    """Return the configured inventory creation function."""

    if _create_inventory is None:
        raise RuntimeError("Inventory create function is not configured.")
    return _create_inventory


def _plans():
    """Return the configured improvement-plan service."""

    if _plans_service is None:
        raise RuntimeError("Improvement plan service is not configured.")
    return _plans_service


def _timeout() -> float:
    """Resolve the shared HTTP timeout from the environment."""

    value = os.environ.get("MS_HTTP_TIMEOUT", "")
    if value == "":
        raise RuntimeError(
            "MS_HTTP_TIMEOUT is not set. Please set it in the environment."
        )
    return float(value)


def _host_file(file: Any) -> dict:
    """Normalize a ChatGPT host file argument to a plain dictionary."""

    if hasattr(file, "model_dump"):
        return file.model_dump()
    if isinstance(file, dict):
        return file
    raise ValueError("file must be an object with download_url and file_id.")


def _inventory_submission_failed() -> None:
    raise RuntimeError("Inventory submission failed. Try again later.")


def _blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_reserved
        or address.is_multicast
    )


def _chatgpt_allowed_hosts() -> set[str]:
    """Return the ChatGPT download host allowlist from the environment."""

    value = os.environ.get("CHATGPT_FILE_ALLOWED_HOSTS", "")
    if value == "":
        raise RuntimeError(
            "CHATGPT_FILE_ALLOWED_HOSTS is not set. Please set it in the environment."
        )
    return {
        part.strip().lower().rstrip(".")
        for part in value.split(",")
        if part.strip()
    }


def _assert_safe_chatgpt_download_url(download_url: str) -> None:
    parsed = urlparse(download_url)
    if parsed.scheme != "https":
        _inventory_submission_failed()
    host = parsed.hostname
    if not isinstance(host, str) or host.strip() == "":
        _inventory_submission_failed()
    lowered = host.lower().rstrip(".")
    if lowered not in _chatgpt_allowed_hosts():
        _inventory_submission_failed()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        _inventory_submission_failed()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and _blocked_ip(literal):
        _inventory_submission_failed()
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        _inventory_submission_failed()
    if not infos:
        _inventory_submission_failed()
    for info in infos:
        try:
            resolved = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            _inventory_submission_failed()
        if _blocked_ip(resolved):
            _inventory_submission_failed()


def _max_chatgpt_file_bytes() -> int:
    value = os.environ.get("CHATGPT_FILE_MAX_BYTES", "")
    if value == "":
        raise RuntimeError(
            "CHATGPT_FILE_MAX_BYTES is not set. Please set it in the environment."
        )
    return int(value)


def _read_chatgpt_file_bytes(response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                _inventory_submission_failed()
            chunks.append(chunk)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    return b"".join(chunks)


def fetch_chatgpt_file(file: dict) -> tuple[bytes, str]:
    """Download an allowlisted ChatGPT-hosted file and return its bytes and name."""

    payload = _host_file(file)
    download_url = payload.get("download_url")
    file_id = payload.get("file_id")
    if not isinstance(download_url, str) or download_url.strip() == "":
        raise ValueError("file.download_url is required.")
    if not isinstance(file_id, str) or file_id.strip() == "":
        raise ValueError("file.file_id is required.")
    _assert_safe_chatgpt_download_url(download_url)
    try:
        response = requests.get(
            download_url,
            timeout=_timeout(),
            stream=True,
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            _inventory_submission_failed()
        response.raise_for_status()
        body = _read_chatgpt_file_bytes(response, _max_chatgpt_file_bytes())
    except requests.RequestException:
        raise RuntimeError("Inventory submission failed. Try again later.") from None
    file_name = payload.get("file_name") or payload.get("fileName") or ""
    return body, file_name


def ingest_chatgpt_inventory(
    id_external_user: int,
    name: str,
    file_name: str,
    file_type: str,
    file_bytes: bytes,
) -> dict:
    """Upload a ChatGPT file to Cloudinary and create an inventory record."""

    identifier = _positive_int(id_external_user, "id_external_user")
    inventory_name = _required_text(name, "name")
    stored_name = _required_text(file_name, "file_name")
    kind = _required_text(file_type, "fileType")
    if kind not in {"IMAGE", "XLSX"}:
        raise ValueError("fileType must be exactly IMAGE or XLSX.")
    if not file_bytes:
        raise ValueError("file bytes must be nonempty.")
    try:
        signature_payload = get_upload_signature(kind)
        path = upload_signed_file(file_bytes, stored_name, signature_payload)
        inventory = _inventory_creator()(inventory_name, stored_name, path)
    except (CloudinaryError, InventoryError) as exc:
        logger.warning("Inventory submission failed: %s", exc)
        raise RuntimeError("Inventory submission failed. Try again later.") from None
    _tickets().record_created_inventory(identifier, inventory["id"])
    return {
        key: inventory[key]
        for key in _inventory_response_keys
        if key in inventory
    }


def _analyze_inventory(
    id_external_user: int,
    name: str | None = None,
    fileName: str | None = None,
    fileType: str | None = None,
    ticket: str | None = None,
) -> dict[str, Any]:
    """Create an upload ticket or submit its uploaded file for analysis."""

    identifier = _positive_int(id_external_user, "id_external_user")
    if ticket is None or (isinstance(ticket, str) and ticket.strip() == ""):
        inventory_name = _required_text(name, "name")
        file_name = _required_text(fileName, "fileName")
        file_type = _required_text(fileType, "fileType")
        if file_type not in {"IMAGE", "XLSX"}:
            raise ValueError("fileType must be exactly IMAGE or XLSX.")
        created = _tickets().create(
            identifier,
            inventory_name,
            file_name,
            file_type,
        )
        return {"ticket": created.ticket, "state": "waiting_for_upload"}

    ticket_value = _required_text(ticket, "ticket")
    uploaded = _tickets().get(identifier, ticket_value)
    if (
        uploaded.state != STATE_UPLOADED
        or not isinstance(uploaded.path, str)
        or uploaded.path.strip() == ""
    ):
        raise ValueError("Ticket upload is not complete.")

    try:
        inventory = _inventory_creator()(
            uploaded.name,
            uploaded.file_name,
            uploaded.path,
        )
    except InventoryError as exc:
        logger.warning("Inventory submission failed: %s", exc)
        raise RuntimeError("Inventory submission failed. Try again later.") from None
    _tickets().mark_consumed(identifier, ticket_value, inventory["id"])
    return {
        key: inventory[key]
        for key in _inventory_response_keys
        if key in inventory
    }


def _analyze_inventory_chatgpt(
    name: str,
    fileType: str,
    file: ChatGPTInventoryFile,
) -> dict:
    """Create an inventory from a ChatGPT-hosted file for the bound user."""

    file_bytes, file_name = fetch_chatgpt_file(file)
    return ingest_chatgpt_inventory(
        current_id_external_user(),
        name,
        file_name,
        fileType,
        file_bytes,
    )


def _get_inventory_analysis(
    id_external_user: int,
    id: int,
) -> dict[str, Any]:
    """Return analysis for an inventory owned by the bound user's company, or PROCESSING."""

    identifier = _positive_int(id_external_user, "id_external_user")
    inventory_id = _positive_int(id, "id")
    if inventory_id not in _tickets().created_inventory_ids(identifier):
        raise ValueError("inventory was not created through this user's upload tickets.")

    try:
        plan = _plans().get_by_id_external_inventory(inventory_id)
    except ValueError:
        return {"status": "PROCESSING"}

    try:
        bound_company = current_id_external_company()
    except RuntimeError:
        bound_company = None
    if bound_company is not None and plan.id_external_company != bound_company:
        raise ValueError("inventory was not created through this user's upload tickets.")

    return {
        "defined_problem": plan.defined_problem,
        "solving_method": plan.method,
        "reasoning": plan.reasoning,
    }


def _typed_tool(name: str, description: str, func: Any) -> Tool:
    """Build a Tool whose schema uses the function's named arguments."""

    return Tool(
        name=name,
        description=description,
        func=func,
        args_schema=create_schema_from_function(name, func),
    )


def get_inventory_ingest_tools() -> list[Tool]:
    """Return typed tools for inventory ingest and analysis polling."""

    return [
        _typed_tool(
            "analyze_inventory",
            ANALYZE_INVENTORY_DESCRIPTION,
            _analyze_inventory,
        ),
        _typed_tool(
            "get_inventory_analysis",
            GET_INVENTORY_ANALYSIS_DESCRIPTION,
            _get_inventory_analysis,
        ),
    ]
