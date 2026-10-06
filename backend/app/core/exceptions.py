"""
Custom exception classes for the application.
"""

from typing import Any, Dict, Optional
from fastapi import HTTPException, status


class AppException(Exception):
    """Base exception for application errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "APP_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(AppException):
    """Raised when validation fails."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "VALIDATION_ERROR", details)


class AuthenticationError(AppException):
    """Raised when authentication fails."""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "AUTHENTICATION_ERROR")


class AuthorizationError(AppException):
    """Raised when authorization fails."""
    
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, "AUTHORIZATION_ERROR")


class ResourceNotFoundError(AppException):
    """Raised when a resource is not found."""
    
    def __init__(self, resource: str, resource_id: Any):
        message = f"{resource} with ID {resource_id} not found"
        super().__init__(message, "RESOURCE_NOT_FOUND", {"resource": resource, "id": resource_id})


class ResourceAlreadyExistsError(AppException):
    """Raised when a resource already exists."""
    
    def __init__(self, resource: str, identifier: str):
        message = f"{resource} with {identifier} already exists"
        super().__init__(message, "RESOURCE_ALREADY_EXISTS", {"resource": resource})


class ExternalServiceError(AppException):
    """Raised when an external service fails."""
    
    def __init__(self, service: str, message: str, details: Optional[Dict[str, Any]] = None):
        full_message = f"{service} error: {message}"
        super().__init__(full_message, "EXTERNAL_SERVICE_ERROR", details or {"service": service})


class OpenAIError(ExternalServiceError):
    """Raised when OpenAI API fails."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("OpenAI", message, details)


class VectorStoreError(ExternalServiceError):
    """Raised when vector store operations fail."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("VectorStore", message, details)


class ScrapingError(ExternalServiceError):
    """Raised when web scraping fails."""
    
    def __init__(self, url: str, message: str):
        super().__init__("Scraper", message, {"url": url})


class ConfigurationError(AppException):
    """Raised when configuration is missing or invalid."""
    
    def __init__(self, message: str, help_text: Optional[str] = None):
        details = {"help_text": help_text} if help_text else {}
        super().__init__(message, "CONFIGURATION_ERROR", details)


class LLMServiceError(ExternalServiceError):
    """Raised when LLM service (Gemini/OpenAI) fails."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        service_details = details or {}
        if status_code:
            service_details["status_code"] = status_code
        super().__init__("LLM", message, service_details)


class IngestionError(AppException):
    """Raised when content ingestion fails."""
    
    def __init__(self, message: str, source_id: Optional[int] = None):
        details = {"source_id": source_id} if source_id else {}
        super().__init__(message, "INGESTION_ERROR", details)


class RateLimitError(AppException):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, message: str = "Rate limit exceeded", retry_after: Optional[int] = None):
        details = {"retry_after": retry_after} if retry_after else {}
        super().__init__(message, "RATE_LIMIT_ERROR", details)


class PaymentError(AppException):
    """Raised when payment processing fails."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "PAYMENT_ERROR", details)



def app_exception_to_http_exception(exc: AppException) -> HTTPException:
    """Convert application exception to HTTP exception."""
    
    status_code_map = {
        "VALIDATION_ERROR": status.HTTP_400_BAD_REQUEST,
        "AUTHENTICATION_ERROR": status.HTTP_401_UNAUTHORIZED,
        "AUTHORIZATION_ERROR": status.HTTP_403_FORBIDDEN,
        "RESOURCE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "RESOURCE_ALREADY_EXISTS": status.HTTP_409_CONFLICT,
        "RATE_LIMIT_ERROR": status.HTTP_429_TOO_MANY_REQUESTS,
        "EXTERNAL_SERVICE_ERROR": status.HTTP_502_BAD_GATEWAY,
        "INGESTION_ERROR": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "PAYMENT_ERROR": status.HTTP_402_PAYMENT_REQUIRED,
        "CONFIGURATION_ERROR": status.HTTP_500_INTERNAL_SERVER_ERROR,
    }

    
    status_code = status_code_map.get(exc.error_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details
        }
    )
