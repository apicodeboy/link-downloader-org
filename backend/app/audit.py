"""Audit log helper. Records who did what, from where, and whether it succeeded."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog

log = logging.getLogger("audit")


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def audit(db: Session, request: Request | None, action: str, *, user_id: int | None = None,
          success: bool = True, target_type: str | None = None, target_id: str | int | None = None,
          **details: Any) -> None:
    entry = AuditLog(
        action=action,
        success=success,
        user_id=user_id,
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:255] if request else None),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details or None,
    )
    db.add(entry)
    db.commit()
    log.info("audit action=%s user=%s success=%s target=%s:%s", action, user_id, success, target_type, target_id)
