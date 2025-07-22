# Changelog

All notable changes to the Orqest framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Standardized error handling system
  - Created a new `errors` module with a comprehensive error class hierarchy
  - Added error severity levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - Added error categories (AGENT, LLM, VALIDATION, TOOL, GENERAL)
  - Added context-rich error messages with agent name, operation, and details
  - Added utility functions for error handling and formatting
  - Added documentation for the error handling system
- Enhanced NoValidResponse class with more detailed error information
- Added helper methods to BaseAgent for standardized error handling
  - _create_error_context: Creates an ErrorContext with agent information
  - _handle_agent_error: Handles errors and returns a NoValidResponse
- Updated PlannerAgent and OrchestratorAgent to use the standardized error handling
- Added comprehensive tests for the error handling system
- Flexible agent composition
  - Created a utility function `create_agent_tool` to wrap any agent as a tool
  - Implemented FlexibleOrchestratorAgent that can use any agent as a tool
  - Added examples demonstrating flexible agent composition
  - Added documentation for flexible agent composition
- RunContext implementation for state passing
  - Updated agents to use RunContext for passing state to tools
  - Eliminated the need for temporary states when calling sub-agents
  - Improved state sharing between agents
  - Updated documentation to explain RunContext usage
- Project restructuring
  - Moved agent implementations to examples/ directory
  - Organized tests into a structured directory hierarchy
  - Added comprehensive documentation in docs/ directory
  - Created a clean project structure with clear separation of concerns

## [0.0.1] - 2025-07-21

### Added
- Initial release of the Orqest framework
- BaseAgent abstract class for creating modular, reusable agents
- PlannerAgent and OrchestratorAgent implementations
- Agent-as-Tools pattern for hierarchical agent composition
- State management using Pydantic models
- Async support for efficient concurrent operations

### Fixed
- Missing `_process_agent_response` implementation in PlannerAgent
  - Added implementation that processes the agent's response, extracts the plan, and updates the state
- Missing `_call_planner_agent` method in OrchestratorAgent
  - Added implementation that creates a temporary state, runs the planner agent, and returns the resulting plan
- Async function call issue in `run_orchestrator()`
  - Fixed by creating a proper async execution flow with a main function and using `asyncio.run()`
- `NoValidResponse` class definition issue
  - Moved the definition to the base_agent.py file and updated the import in orchestrator_and_planner.py
- Missing `_process_agent_response` in OrchestratorAgent
  - Added implementation to handle responses properly

### Improved
- Enhanced error handling
  - Both agent implementations now properly handle invalid responses and provide appropriate error messages
- Consistent code structure
  - Ensured consistent implementation of abstract methods across all agent classes
  - Standardized the approach to processing agent responses
- Proper async flow
  - Implemented proper async/await patterns throughout the codebase
  - Added a main function with asyncio.run() to ensure correct execution of async code
- Expanded documentation
  - Added detailed information about the framework's purpose and capabilities
  - Documented how agents can be used as tools for other agents
  - Described architecture and key concepts
  - Included usage examples and getting started guide
- Added testing
  - Created a test script (test_orchestrator_and_planner.py) to verify the fixes
  - Tests confirm that both the PlannerAgent and OrchestratorAgent work correctly

### Verified
- All changes have been tested and verified to work correctly
- The test script successfully runs both agents and confirms that they can:
  - Process user queries
  - Generate plans
  - Update state appropriately
  - Handle errors gracefully
- The framework now provides a solid foundation for building scalable agent systems where agents can be dynamically assigned as tools to other agents without hardcoded graphs