# Changelog

All notable changes to the Orqest framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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