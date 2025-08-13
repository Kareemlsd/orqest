"""Hook system for Orqest agents.

This module provides the hook system for Orqest agents, including:
- Hook points for agent lifecycle events
- Hook registry for registering hooks
- Hook execution logic
- Middleware support for cross-cutting concerns
"""
import asyncio
import functools
import inspect
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, TypeVar, Union, cast

from pydantic import BaseModel

# Type variable for the state
StateT = TypeVar("StateT", bound=BaseModel)
# Type variable for the result
ResultT = TypeVar("ResultT")
# Type for hook functions
HookFunc = Callable[..., Any]


class HookPoint(str, Enum):
    """Enum for hook points in the agent lifecycle."""
    PRE_RUN = "pre_run"
    POST_RUN = "post_run"
    PRE_PROCESS_RESPONSE = "pre_process_response"
    POST_PROCESS_RESPONSE = "post_process_response"
    ON_ERROR = "on_error"


class HookRegistry:
    """Registry for hooks.
    
    This class provides methods for registering and executing hooks at different
    hook points in the agent lifecycle.
    """
    
    def __init__(self):
        """Initialize the hook registry."""
        self._hooks: Dict[HookPoint, List[Dict[str, Any]]] = {
            hook_point: [] for hook_point in HookPoint
        }
    
    def add_hook(
        self, 
        hook_point: Union[HookPoint, str], 
        hook_func: HookFunc, 
        priority: int = 0,
        name: Optional[str] = None
    ) -> None:
        """Add a hook to the registry.
        
        Args:
            hook_point: The hook point to register the hook for.
            hook_func: The hook function to register.
            priority: The priority of the hook (higher priority hooks are executed first).
            name: Optional name for the hook (defaults to the function name).
        """
        if isinstance(hook_point, str):
            hook_point = HookPoint(hook_point)
            
        hook_name = name or hook_func.__name__
        
        # Check if the hook is already registered
        for hook in self._hooks[hook_point]:
            if hook["name"] == hook_name:
                # Update the existing hook
                hook["func"] = hook_func
                hook["priority"] = priority
                return
        
        # Add the hook
        self._hooks[hook_point].append({
            "name": hook_name,
            "func": hook_func,
            "priority": priority
        })
        
        # Sort hooks by priority (descending)
        self._hooks[hook_point].sort(key=lambda h: h["priority"], reverse=True)
    
    def remove_hook(self, hook_point: Union[HookPoint, str], name: str) -> bool:
        """Remove a hook from the registry.
        
        Args:
            hook_point: The hook point to remove the hook from.
            name: The name of the hook to remove.
            
        Returns:
            True if the hook was removed, False otherwise.
        """
        if isinstance(hook_point, str):
            hook_point = HookPoint(hook_point)
            
        for i, hook in enumerate(self._hooks[hook_point]):
            if hook["name"] == name:
                self._hooks[hook_point].pop(i)
                return True
        
        return False
    
    def get_hooks(self, hook_point: Union[HookPoint, str]) -> List[Dict[str, Any]]:
        """Get all hooks for a hook point.
        
        Args:
            hook_point: The hook point to get hooks for.
            
        Returns:
            A list of hooks for the hook point.
        """
        if isinstance(hook_point, str):
            hook_point = HookPoint(hook_point)
            
        return self._hooks[hook_point]

    async def execute_hooks(
            self,
            hook_point: Union[HookPoint, str],
            *args: Any,
            **kwargs: Any
    ) -> Any:
        """Execute all hooks for a hook point."""
        if isinstance(hook_point, str):
            hook_point = HookPoint(hook_point)

        hooks = self._hooks[hook_point]

        # If no hooks are registered
        if not hooks and args:
            # Special case for response-processing hooks: always return a tuple
            if hook_point in {HookPoint.PRE_PROCESS_RESPONSE, HookPoint.POST_PROCESS_RESPONSE}:
                if len(args) >= 2:
                    return args[0], args[1]  # (response, state)
                else:
                    raise ValueError(f"{hook_point} requires at least (response, state) arguments.")
            return args[0]

        # Execute hooks in priority order
        result = args[0] if args else None

        for hook in hooks:
            hook_func = hook["func"]

            if inspect.iscoroutinefunction(hook_func):
                result = await hook_func(*args, **kwargs)
            else:
                result = hook_func(*args, **kwargs)

        return result

class Middleware:
    """Base class for middleware.
    
    Middleware provides a way to inject logic at multiple hook points in the agent lifecycle.
    Subclasses can override methods for specific hook points.
    """
    
    async def pre_run(self, state: BaseModel, **kwargs: Any) -> BaseModel:
        """Execute before the agent's run method is called.
        
        Args:
            state: The state to be passed to the agent's run method.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The state to be passed to the agent's run method.
        """
        return state
    
    async def post_run(self, state: BaseModel, result: Any, **kwargs: Any) -> Any:
        """Execute after the agent's run method is called.
        
        Args:
            state: The state that was passed to the agent's run method.
            result: The result of the agent's run method.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The result to be returned from the agent's run method.
        """
        return result
    
    async def pre_process_response(self, response: Any, state: BaseModel, **kwargs: Any) -> tuple[Any, BaseModel]:
        """Execute before the agent's _process_agent_response method is called.
        
        Args:
            response: The response to be processed.
            state: The state to be passed to the _process_agent_response method.
            **kwargs: Additional keyword arguments.
            
        Returns:
            A tuple of (response, state) to be passed to the _process_agent_response method.
        """
        return response, state
    
    async def post_process_response(self, response: Any, state: BaseModel, result: Any, **kwargs: Any) -> Any:
        """Execute after the agent's _process_agent_response method is called.
        
        Args:
            response: The response that was processed.
            state: The state that was passed to the _process_agent_response method.
            result: The result of the _process_agent_response method.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The result to be returned from the _process_agent_response method.
        """
        return result
    
    async def on_error(self, error: Exception, state: BaseModel, operation: str, **kwargs: Any) -> Any:
        """Execute when an error occurs during the agent's execution.
        
        Args:
            error: The exception that occurred.
            state: The state that was being processed.
            operation: The operation being performed when the error occurred.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The result to be returned from the agent's method.
        """
        # By default, re-raise the error
        raise error


def hook(hook_point: Union[HookPoint, str], priority: int = 0):
    """Decorator for registering a method as a hook.
    
    Args:
        hook_point: The hook point to register the method for.
        priority: The priority of the hook (higher priority hooks are executed first).
        
    Returns:
        A decorator that registers the method as a hook.
    """
    def decorator(func):
        # Set an attribute on the function to mark it as a hook
        setattr(func, "_hook_point", hook_point)
        setattr(func, "_hook_priority", priority)
        return func
    return decorator