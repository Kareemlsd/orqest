# Orqest Tutorials

This directory contains Jupyter notebook tutorials for the Orqest framework. These tutorials are designed to help you learn how to use Orqest to build advanced agentic workflows.

## Tutorial Structure

The tutorials are organized in a progressive manner, starting with basic concepts and moving to more advanced topics:

1. **Getting Started**: Introduction to the Orqest framework and basic concepts
2. **Creating Custom Agents**: How to extend the BaseAgent class to create your own agents
3. **State Management**: Working with state models in Orqest
4. **Agent Composition**: Using agents as tools for other agents
5. **Lifecycle Hooks**: Injecting custom logic at different points in an agent's lifecycle
6. **Error Handling**: Creating robust agents that handle errors gracefully
7. **Flexible Orchestration**: Building dynamic orchestration patterns without hardcoded agent graphs

## Prerequisites

To run these tutorials, you'll need:

1. Python 3.12 or higher
2. Jupyter Notebook or JupyterLab
3. The Orqest framework and its dependencies

## Installation

1. Install Jupyter:
   ```
   pip install jupyter
   ```

2. Install Orqest:
   ```
   pip install orqest
   ```

3. Set up your OpenAI API key in a `.env` file:
   ```
   LLM_API_KEY=your_openai_api_key
   LLM_MODEL=gpt-3.5-turbo  # or another OpenAI model
   ```

## Running the Tutorials

The tutorials are available as Python scripts (.py files) with special cell markers in the `notebooks` directory. These scripts are designed to be viewed and run as notebooks in compatible IDEs like VS Code or PyCharm.

### Using VS Code

1. Install the Python extension for VS Code if you haven't already.
2. Open any tutorial script (e.g., `01_getting_started.py`) in VS Code.
3. VS Code will automatically recognize the cell markers and display the file as a notebook.
4. You can run cells individually by clicking the "Run Cell" button that appears above each cell.

### Using PyCharm

1. Open any tutorial script in PyCharm.
2. PyCharm will recognize the cell markers and display the "Run Cell" gutter icons.
3. Click on these icons to run individual cells.

### Using Jupyter Notebook

If you prefer to use Jupyter Notebook, you can convert the Python scripts to .ipynb files:

1. Install Jupyter if you haven't already:
   ```
   pip install jupyter nbconvert
   ```

2. Convert a Python script to a notebook:
   ```
   jupyter nbconvert --to notebook --execute docs/tutorials/notebooks/01_getting_started.py
   ```

3. Open the generated .ipynb file with Jupyter:
   ```
   jupyter notebook docs/tutorials/notebooks/01_getting_started.ipynb
   ```

## Understanding the Cell Markers

The tutorial scripts use special cell markers to define code and markdown cells:

- `#%% md` marks the beginning of a markdown cell
- `#%%` marks the beginning of a code cell

These markers allow the scripts to be viewed and run as notebooks in compatible IDEs while still being valid Python files.

## Running the Code

You can run the tutorial scripts in several ways:

1. **As notebooks**: Run individual cells as described above.
2. **As Python scripts**: Run the entire script using Python:
   ```
   python docs/tutorials/notebooks/01_getting_started.py
   ```
3. **In an interactive Python session**: Import and run functions from the scripts.

## Testing the Tutorials

To test that the tutorials run correctly, you can execute each script:

```
python docs/tutorials/notebooks/01_getting_started.py
python docs/tutorials/notebooks/02_creating_custom_agents.py
# ... and so on
```

Or you can write a simple test script that imports and runs the main function from each tutorial.

## Tutorial Descriptions

### 1. Getting Started
An introduction to the Orqest framework, including installation, basic concepts, and a simple example of creating and running an agent.

### 2. Creating Custom Agents
Learn how to extend the BaseAgent class to create your own specialized agents, implement the required methods, and add tools.

### 3. State Management
Understand how to define state models with Pydantic, validate and transform state, manage conversation history, and share state between agents.

### 4. Agent Composition
Discover how to create agent tools, use RunContext for state passing, compose agents hierarchically, and build dynamic orchestration patterns.

### 5. Lifecycle Hooks
Explore how to inject custom logic at different points in an agent's lifecycle, use middleware for cross-cutting concerns, and create reusable hooks.

### 6. Error Handling
Learn how to create robust agents that handle errors gracefully, use the error hierarchy, create and handle errors, and use error context.

### 7. Flexible Orchestration
Build dynamic orchestration patterns without hardcoded agent graphs, using the FlexibleOrchestratorAgent and agent tools.