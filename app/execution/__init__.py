"""Execution layer - Execute recommended actions on cloud resources.

Provides safe, reliable action execution with:
- Retry logic (up to 3 attempts)
- Error handling and recovery
- Comprehensive logging
- Dry-run mode for testing
- Audit trail
"""

from app.execution.aws_executor import AWSExecutor, ExecutionResult, ExecutionStatus

__all__ = ["AWSExecutor", "ExecutionResult", "ExecutionStatus"]
