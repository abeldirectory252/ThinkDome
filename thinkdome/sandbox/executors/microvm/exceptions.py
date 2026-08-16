"""Custom domain exceptions for MicroVM execution and host networking."""

class MicroVMError(Exception):
    """Base exception for all MicroVM operations."""
    pass

class InsufficientPrivilegesError(MicroVMError):
    """Raised when root (UID 0) or CAP_NET_ADMIN capabilities are missing."""
    pass

class TAPDeviceError(MicroVMError):
    """Raised when TAP network interface allocation or cleanup fails."""
    pass

class NetworkConfigurationError(MicroVMError):
    """Raised when Linux bridge or iptables configuration fails."""
    pass

class MicroVMProvisionError(MicroVMError):
    """Raised when MicroVM instance spawning or booting fails."""
    pass
