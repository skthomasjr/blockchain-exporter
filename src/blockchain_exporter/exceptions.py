"""Custom exception hierarchy for blockchain exporter."""

from __future__ import annotations


class BlockchainExporterError(Exception):
    """Base exception for all blockchain exporter errors.

    All custom exceptions in this module inherit from this base class.
    This allows catching all exporter-specific errors while preserving
    the exception hierarchy for more specific error handling.
    """

    def __init__(
        self,
        message: str,
        *,
        context: dict[str, object] | None = None,
    ) -> None:
        """Initialize the exception with a message and optional context.

        Args:
            message: The error message.
            context: Optional context dictionary with additional error information.
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        """Return a string representation of the exception."""
        if self.context:
            context_str = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{self.message} (context: {context_str})"
        return self.message


class RpcError(BlockchainExporterError):
    """Base exception for RPC-related errors.

    Raised when RPC operations fail due to network issues, timeouts,
    or RPC protocol errors.
    """

    def __init__(
        self,
        message: str,
        *,
        blockchain: str | None = None,
        rpc_url: str | None = None,
        operation: str | None = None,
        attempt: int | None = None,
        max_attempts: int | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        """Initialize the RPC error with context.

        Args:
            message: The error message.
            blockchain: The blockchain name.
            rpc_url: The RPC URL.
            operation: The RPC operation that failed.
            attempt: The attempt number (for retries).
            max_attempts: The maximum number of attempts.
            context: Optional additional context.
        """
        rpc_context: dict[str, object] = {}
        if blockchain:
            rpc_context["blockchain"] = blockchain
        if rpc_url:
            rpc_context["rpc_url"] = rpc_url
        if operation:
            rpc_context["operation"] = operation
        if attempt is not None:
            rpc_context["attempt"] = attempt
        if max_attempts is not None:
            rpc_context["max_attempts"] = max_attempts
        if context:
            rpc_context.update(context)

        super().__init__(message, context=rpc_context)
        self.blockchain = blockchain
        self.rpc_url = rpc_url
        self.operation = operation
        self.attempt = attempt
        self.max_attempts = max_attempts


class RpcConnectionError(RpcError):
    """Raised when unable to connect to an RPC endpoint."""

    pass


class RpcTimeoutError(RpcError):
    """Raised when an RPC operation times out."""

    pass


class RpcProtocolError(RpcError):
    """Raised when an RPC protocol error occurs (e.g., JSON-RPC error response)."""

    def __init__(
        self,
        message: str,
        *,
        rpc_error_code: int | None = None,
        rpc_error_message: str | None = None,
        **kwargs: object,
    ) -> None:
        """Initialize the RPC protocol error.

        Args:
            message: The error message.
            rpc_error_code: The RPC error code.
            rpc_error_message: The RPC error message.
            **kwargs: Additional arguments passed to RpcError.
        """
        context = kwargs.pop("context", {}) or {}
        if rpc_error_code is not None:
            context["rpc_error_code"] = rpc_error_code
        if rpc_error_message:
            context["rpc_error_message"] = rpc_error_message
        kwargs["context"] = context
        super().__init__(message, **kwargs)
        self.rpc_error_code = rpc_error_code
        self.rpc_error_message = rpc_error_message


class ConfigError(BlockchainExporterError):
    """Base exception for configuration-related errors.

    Raised when configuration files cannot be loaded, parsed, or validated.
    """

    def __init__(
        self,
        message: str,
        *,
        config_file: str | None = None,
        config_section: str | None = None,
        config_key: str | None = None,
        line_number: int | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        """Initialize the configuration error with context.

        Args:
            message: The error message.
            config_file: The configuration file path.
            config_section: The configuration section (e.g., "blockchains[0]").
            config_key: The configuration key.
            line_number: The line number in the configuration file.
            context: Optional additional context.
        """
        config_context: dict[str, object] = {}
        if config_file:
            config_context["config_file"] = config_file
        if config_section:
            config_context["config_section"] = config_section
        if config_key:
            config_context["config_key"] = config_key
        if line_number is not None:
            config_context["line_number"] = line_number
        if context:
            config_context.update(context)

        super().__init__(message, context=config_context)
        self.config_file = config_file
        self.config_section = config_section
        self.config_key = config_key
        self.line_number = line_number


class ValidationError(ConfigError):
    """Raised when configuration validation fails.

    This is a subclass of ConfigError to maintain the exception hierarchy
    while providing a more specific error type for validation failures.
    """

    def __init__(
        self,
        message: str,
        *,
        value: object | None = None,
        expected_type: str | None = None,
        **kwargs: object,
    ) -> None:
        """Initialize the validation error.

        Args:
            message: The error message.
            value: The invalid value.
            expected_type: The expected type.
            **kwargs: Additional arguments passed to ConfigError.
        """
        context = kwargs.pop("context", {}) or {}
        if value is not None:
            context["value"] = value
        if expected_type:
            context["expected_type"] = expected_type
        kwargs["context"] = context
        super().__init__(message, **kwargs)
        self.value = value
        self.expected_type = expected_type


__all__ = [
    "BlockchainExporterError",
    "ConfigError",
    "RpcConnectionError",
    "RpcError",
    "RpcProtocolError",
    "RpcTimeoutError",
    "ValidationError",
]
