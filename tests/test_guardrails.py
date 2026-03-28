"""Tests for safety guardrails."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.models.resource import Resource, ResourceStatus, ResourceType
from app.safety.guardrails import (
    CircuitBreakerState,
    SafetyResult,
    rollback_required_for_delete,
    validate_before_execution,
)


def _resource(**kwargs) -> Resource:
    defaults = dict(
        id=1,
        name="r1",
        type=ResourceType.ec2,
        region="us-east-1",
        status=ResourceStatus.running,
        provider="aws",
        external_id="i-abc",
        tags_json=json.dumps({}),
    )
    defaults.update(kwargs)
    r = Resource()
    for k, v in defaults.items():
        setattr(r, k, v)
    return r


def test_tag_filter_requires_managed():
    db = MagicMock()
    db.scalar.return_value = None
    r = _resource(tags_json=json.dumps({"costintel-managed": "false"}))
    with patch("app.safety.guardrails.get_circuit_breaker") as gcb:
        gcb.return_value = CircuitBreakerState(failure_threshold=99, window_seconds=300)
        out = validate_before_execution(db, r, "stop_instance")
    assert out.allowed is False
    assert any("Tag filter" in x for x in out.reasons)


def test_tag_filter_allows_managed():
    db = MagicMock()
    db.scalar.return_value = None
    r = _resource(tags_json=json.dumps({"costintel-managed": "true"}))
    with patch("app.safety.guardrails.get_circuit_breaker") as gcb:
        gcb.return_value = CircuitBreakerState(failure_threshold=99, window_seconds=300)
        out = validate_before_execution(db, r, "stop_instance", dry_run=True)
    assert out.allowed is True


def test_circuit_breaker_blocks():
    db = MagicMock()
    db.scalar.return_value = None
    r = _resource(tags_json=json.dumps({"costintel-managed": "true"}))
    cb = CircuitBreakerState(failure_threshold=1, window_seconds=300)
    cb.record_failure()
    with patch("app.safety.guardrails.get_circuit_breaker", return_value=cb):
        out = validate_before_execution(db, r, "stop_instance", dry_run=True)
    assert out.allowed is False
    assert any("Circuit breaker" in x for x in out.reasons)


def test_dependency_blocks_when_dependent_running():
    db = MagicMock()
    db.scalar.return_value = None
    vol = _resource(
        id=2,
        name="vol",
        type=ResourceType.ec2,
        external_id="vol-xyz",
        tags_json=json.dumps({"costintel-managed": "true"}),
    )
    dep = _resource(
        id=3,
        name="app",
        external_id="i-other",
        tags_json=json.dumps(
            {
                "costintel-managed": "true",
                "costintel-depends-on": json.dumps(["vol-xyz"]),
            }
        ),
    )
    sr = MagicMock()
    sr.all.return_value = [dep]
    db.scalars.return_value = sr
    with patch("app.safety.guardrails.get_circuit_breaker") as gcb:
        gcb.return_value = CircuitBreakerState(failure_threshold=99, window_seconds=300)
        out = validate_before_execution(db, vol, "delete_volume", skip_rollback_check=True)
    assert out.allowed is False
    assert any("Dependency check" in x for x in out.reasons)


def test_rollback_required_for_ebs_delete():
    r = _resource(
        type=ResourceType.ec2,
        external_id="vol-abc123",
        tags_json=json.dumps({"costintel-managed": "true"}),
    )
    assert rollback_required_for_delete(r, "delete_volume") is True
    assert rollback_required_for_delete(r, "stop_instance") is False


def test_safety_result_add():
    s = SafetyResult(allowed=True)
    s.add(False, "bad")
    assert s.allowed is False
    assert "bad" in s.reasons
