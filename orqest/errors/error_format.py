"""Standardized error formatting for Orqest framework.

This module defines a standardized error formatting for the Orqest framework,
including error categories, severity levels, and context information.
"""
import enum
import datetime
import traceback
from typing import Any, Dict, Optional, Type


class ErrorSeverity(enum.Enum):
    """Severity levels for errors.
    
    Attributes:
        DEBUG: Low severity, for debugging purposes.
        INFO: Informational, not an error but noteworthy.
        WARNING: Potential issue that doesn't prevent operation.
        ERROR: Serious issue that prevents successful operation.
        CRITICAL: Critical issue that requires immediate attention.
    """
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class ErrorCategory(enum.Enum):
    """Categories of errors.
    
    Attributes:
        AGENT: Errors related to agent operations.
        LLM: Errors related to LLM operations.
        VALIDATION: Errors related to data validation.
        TOOL: Errors related to tool execution.
        GENERAL: General errors that don't fit other categories.
    """
    AGENT = "agent"
    LLM = "llm"
    VALIDATION = "validation"
    TOOL = "tool"
    GENERAL = "general"


class ErrorContext:
    """Context information for errors.
    
    Attributes:
        agent_name: Name of the agent where the error occurred.
        operation: Operation being performed when the error occurred.
        details: Additional details about the error context.
        timestamp: When the error occurred.
    """
    
    def __init__(
        self,
        agent_name: str,
        operation: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """Initialize the error context.
        
        Args:
            agent_name: Name of the agent where the error occurred.
            operation: Operation being performed when the error occurred.
            details: Additional details about the error context.
        """
        self.agent_name = agent_name
        self.operation = operation
        self.details = details or {}
        self.timestamp = datetime.datetime.now()


class OrqestError(Exception):
    """Base class for all Orqest errors.
    
    Attributes:
        message: Human-readable error message.
        severity: Severity level of the error.
        category: Category of the error.
        context: Context information for the error.
        exception: Original exception that caused this error, if any.
    """
    
    def __init__(
        self,
        message: str,
        severity: ErrorSeverity,
        category: ErrorCategory,
        context: ErrorContext,
        exception: Optional[Exception] = None
    ):
        """Initialize the error.
        
        Args:
            message: Human-readable error message.
            severity: Severity level of the error.
            category: Category of the error.
            context: Context information for the error.
            exception: Original exception that caused this error, if any.
        """
        super().__init__(message)
        self.message = message
        self.severity = severity
        self.category = category
        self.context = context
        self.exception = exception
        
    def __str__(self) -> str:
        """Return a string representation of the error."""
        return self.message


class AgentError(OrqestError):
    """Error related to agent operations.
    
    This error is raised when an agent encounters an issue during execution,
    such as failing to process a response or encountering an unexpected state.
    """
    
    def __init__(
        self,
        message: str,
        severity: ErrorSeverity,
        context: ErrorContext,
        exception: Optional[Exception] = None
    ):
        """Initialize the agent error.
        
        Args:
            message: Human-readable error message.
            severity: Severity level of the error.
            context: Context information for the error.
            exception: Original exception that caused this error, if any.
        """
        super().__init__(
            message=message,
            severity=severity,
            category=ErrorCategory.AGENT,
            context=context,
            exception=exception
        )


class LLMError(OrqestError):
    """Error related to LLM operations.
    
    This error is raised when there's an issue with the LLM, such as
    API errors, rate limiting, or invalid responses.
    """
    
    def __init__(
        self,
        message: str,
        severity: ErrorSeverity,
        context: ErrorContext,
        exception: Optional[Exception] = None
    ):
        """Initialize the LLM error.
        
        Args:
            message: Human-readable error message.
            severity: Severity level of the error.
            context: Context information for the error.
            exception: Original exception that caused this error, if any.
        """
        super().__init__(
            message=message,
            severity=severity,
            category=ErrorCategory.LLM,
            context=context,
            exception=exception
        )


class ValidationError(OrqestError):
    """Error related to data validation.
    
    This error is raised when data validation fails, such as
    invalid state format or missing required fields.
    """
    
    def __init__(
        self,
        message: str,
        severity: ErrorSeverity,
        context: ErrorContext,
        exception: Optional[Exception] = None
    ):
        """Initialize the validation error.
        
        Args:
            message: Human-readable error message.
            severity: Severity level of the error.
            context: Context information for the error.
            exception: Original exception that caused this error, if any.
        """
        super().__init__(
            message=message,
            severity=severity,
            category=ErrorCategory.VALIDATION,
            context=context,
            exception=exception
        )


class ToolError(OrqestError):
    """Error related to tool execution.
    
    This error is raised when a tool fails to execute properly,
    such as failing to call another agent or access a resource.
    """
    
    def __init__(
        self,
        message: str,
        severity: ErrorSeverity,
        context: ErrorContext,
        exception: Optional[Exception] = None
    ):
        """Initialize the tool error.
        
        Args:
            message: Human-readable error message.
            severity: Severity level of the error.
            context: Context information for the error.
            exception: Original exception that caused this error, if any.
        """
        super().__init__(
            message=message,
            severity=severity,
            category=ErrorCategory.TOOL,
            context=context,
            exception=exception
        )


def format_error_message(error: OrqestError) -> str:
    """Format an error message with context information.
    
    Args:
        error: The error to format.
        
    Returns:
        A formatted error message string.
    """
    # Format the basic error information
    formatted_message = (
        f"[{error.severity.name}] {error.category.value.upper()}: {error.message}\n"
        f"Agent: {error.context.agent_name}"
    )
    
    # Add operation if available
    if error.context.operation:
        formatted_message += f"\nOperation: {error.context.operation}"
    
    # Add details if available
    if error.context.details:
        details_str = "\n".join(f"  {k}: {v}" for k, v in error.context.details.items())
        formatted_message += f"\nDetails:\n{details_str}"
    
    # Add exception information if available
    if error.exception:
        formatted_message += f"\nException: {type(error.exception).__name__}: {str(error.exception)}"
        formatted_message += f"\nTraceback:\n{''.join(traceback.format_tb(error.exception.__traceback__))}"
    
    return formatted_message