"""Custom exceptions for i3nator."""


class I3natorError(Exception):
    """Base exception for all i3nator errors."""


class ConfigError(I3natorError):
    """Raised when a layout config file is invalid or cannot be loaded."""


class ConfigNotFoundError(ConfigError):
    """Raised when a named layout config does not exist."""


class ValidationError(ConfigError):
    """Raised when a layout config fails schema validation."""


class WorkspaceError(I3natorError):
    """Raised when a workspace operation fails."""


class WorkspaceOccupiedError(WorkspaceError):
    """Raised when the target workspace already has windows and --force is not set."""


class LaunchError(I3natorError):
    """Raised when a window fails to launch or be detected."""


class LaunchTimeoutError(LaunchError):
    """Raised when a window does not appear within the expected timeout."""


class LayoutError(I3natorError):
    """Raised when the layout engine encounters an unrecoverable error."""
