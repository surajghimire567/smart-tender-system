"""Audit log API and append-only write service."""
from app.audit.service import log_action

__all__ = ["log_action"]
