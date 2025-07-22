"""Test cases for the Orqest error handling module."""
import pytest
import logging
from pathlib import Path

from orqest.errors import (
    ErrorSeverity,
    ErrorCategory,
    ErrorContext,
    OrqestError,
    AgentError,
    LLMError,
    ValidationError,
    ToolError,
    format_error_message
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_error_severity_enum():
    """Test that ErrorSeverity enum has the expected values."""
    assert ErrorSeverity.DEBUG.value < ErrorSeverity.INFO.value
    assert ErrorSeverity.INFO.value < ErrorSeverity.WARNING.value
    assert ErrorSeverity.WARNING.value < ErrorSeverity.ERROR.value
    assert ErrorSeverity.ERROR.value < ErrorSeverity.CRITICAL.value


def test_error_category_enum():
    """Test that ErrorCategory enum has the expected values."""
    assert ErrorCategory.AGENT.value != ErrorCategory.LLM.value
    assert ErrorCategory.LLM.value != ErrorCategory.VALIDATION.value
    assert ErrorCategory.VALIDATION.value != ErrorCategory.TOOL.value
    assert ErrorCategory.TOOL.value != ErrorCategory.GENERAL.value


def test_error_context_creation():
    """Test creating an ErrorContext with various parameters."""
    context = ErrorContext(
        agent_name="test_agent",
        operation="run",
        details={"input": "test input", "output": "test output"}
    )
    
    assert context.agent_name == "test_agent"
    assert context.operation == "run"
    assert context.details["input"] == "test input"
    assert context.details["output"] == "test output"
    assert context.timestamp is not None


def test_orqest_error_base_class():
    """Test the OrqestError base class."""
    error = OrqestError(
        message="Test error message",
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.GENERAL,
        context=ErrorContext(agent_name="test_agent")
    )
    
    assert error.message == "Test error message"
    assert error.severity == ErrorSeverity.ERROR
    assert error.category == ErrorCategory.GENERAL
    assert error.context.agent_name == "test_agent"
    assert str(error) == "Test error message"


def test_agent_error_subclass():
    """Test the AgentError subclass."""
    error = AgentError(
        message="Agent failed to process response",
        severity=ErrorSeverity.ERROR,
        context=ErrorContext(agent_name="test_agent", operation="process_response")
    )
    
    assert error.message == "Agent failed to process response"
    assert error.severity == ErrorSeverity.ERROR
    assert error.category == ErrorCategory.AGENT
    assert error.context.agent_name == "test_agent"
    assert error.context.operation == "process_response"


def test_llm_error_subclass():
    """Test the LLMError subclass."""
    error = LLMError(
        message="LLM API request failed",
        severity=ErrorSeverity.ERROR,
        context=ErrorContext(agent_name="test_agent", operation="run")
    )
    
    assert error.message == "LLM API request failed"
    assert error.severity == ErrorSeverity.ERROR
    assert error.category == ErrorCategory.LLM
    assert error.context.agent_name == "test_agent"


def test_validation_error_subclass():
    """Test the ValidationError subclass."""
    error = ValidationError(
        message="Invalid state format",
        severity=ErrorSeverity.WARNING,
        context=ErrorContext(agent_name="test_agent", operation="validate_state")
    )
    
    assert error.message == "Invalid state format"
    assert error.severity == ErrorSeverity.WARNING
    assert error.category == ErrorCategory.VALIDATION
    assert error.context.agent_name == "test_agent"


def test_tool_error_subclass():
    """Test the ToolError subclass."""
    error = ToolError(
        message="Tool execution failed",
        severity=ErrorSeverity.ERROR,
        context=ErrorContext(agent_name="test_agent", operation="execute_tool", details={"tool_name": "test_tool"})
    )
    
    assert error.message == "Tool execution failed"
    assert error.severity == ErrorSeverity.ERROR
    assert error.category == ErrorCategory.TOOL
    assert error.context.agent_name == "test_agent"
    assert error.context.details["tool_name"] == "test_tool"


def test_format_error_message():
    """Test the format_error_message utility function."""
    error = AgentError(
        message="Agent failed to process response",
        severity=ErrorSeverity.ERROR,
        context=ErrorContext(agent_name="test_agent", operation="process_response")
    )
    
    formatted_message = format_error_message(error)
    
    assert "ERROR" in formatted_message
    assert "AGENT" in formatted_message
    assert "test_agent" in formatted_message
    assert "process_response" in formatted_message
    assert "Agent failed to process response" in formatted_message


def test_error_with_exception_info():
    """Test creating an error with exception information."""
    try:
        # Cause a deliberate exception
        1 / 0
    except Exception as e:
        error = OrqestError(
            message="An exception occurred",
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.GENERAL,
            context=ErrorContext(agent_name="test_agent"),
            exception=e
        )
        
        assert error.message == "An exception occurred"
        assert error.exception is not None
        assert isinstance(error.exception, ZeroDivisionError)
        assert "division by zero" in str(error.exception)