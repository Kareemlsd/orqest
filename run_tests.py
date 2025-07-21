#!/usr/bin/env python
"""Script to run tests for the Orqest framework.

This script demonstrates how to run tests for the Orqest framework using pytest.
It provides options for running all tests, tests for a specific module, or a
specific test file.

Examples:
    # Run all tests
    python run_tests.py
    
    # Run tests for a specific module
    python run_tests.py agents
    
    # Run a specific test file
    python run_tests.py agents/test_planner.py
"""
import sys
import subprocess
from pathlib import Path

def run_tests(module=None, test_file=None):
    """Run tests using pytest.
    
    Args:
        module: Optional module name to test (e.g., 'agents', 'errors').
        test_file: Optional test file to run (e.g., 'agents/test_planner.py').
    
    Returns:
        The return code from pytest.
    """
    # Build the command
    cmd = ["python", "-m", "pytest"]
    
    # Add verbosity flag
    cmd.append("-v")
    
    # Add the test path
    if test_file:
        cmd.append(f"tests/{test_file}")
    elif module:
        cmd.append(f"tests/{module}")
    else:
        cmd.append("tests/")
    
    # Print the command
    print(f"Running: {' '.join(cmd)}")
    print("-" * 80)
    
    # Run the command
    return subprocess.call(cmd)

def main():
    """Parse arguments and run tests."""
    # Check if a module or test file was specified
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        
        # Check if it's a test file
        if arg.endswith(".py"):
            return run_tests(test_file=arg)
        else:
            return run_tests(module=arg)
    else:
        # Run all tests
        return run_tests()

if __name__ == "__main__":
    sys.exit(main())