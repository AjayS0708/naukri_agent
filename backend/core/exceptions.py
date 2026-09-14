from enum import StrEnum


class ErrorCategory(StrEnum):
    AUTH = "AUTH_ERROR"
    SECURITY = "SECURITY_ERROR"
    BROWSER = "BROWSER_ERROR"
    NETWORK = "NETWORK_ERROR"
    NAUKRI = "NAUKRI_ERROR"
    AI = "AI_ERROR"
    AI_QUOTA = "AI_QUOTA_ERROR"
    VALIDATION = "VALIDATION_ERROR"
    APPLICATION = "APPLICATION_ERROR"
    DATABASE = "DATABASE_ERROR"
    CONFIGURATION = "CONFIGURATION_ERROR"


class ApplicationError(Exception):
    category = ErrorCategory.APPLICATION
    status_code = 500

    def __init__(self, message: str = "An application error occurred.") -> None:
        self.message = message
        super().__init__(message)


class DatabaseError(ApplicationError):
    category = ErrorCategory.DATABASE
    status_code = 503


class ValidationError(ApplicationError):
    category = ErrorCategory.VALIDATION
    status_code = 422


class ProfileExtractionError(ApplicationError):
    category = ErrorCategory.AI
    status_code = 502


class AIConfigurationError(ApplicationError):
    category = ErrorCategory.CONFIGURATION
    status_code = 503


class AIQuotaExceededError(ApplicationError):
    category = ErrorCategory.AI_QUOTA
    status_code = 503


class AIUnavailableError(ApplicationError):
    category = ErrorCategory.AI
    status_code = 503
