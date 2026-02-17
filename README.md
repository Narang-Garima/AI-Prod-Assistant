# Commands Followed for UV Environment Setup on Windows

```bash


# Verify Python installation and paths
python
>>> import shutil
>>> print(shutil.which("uv"))
>>> exit()

# Initialize a uv project in current directory
uv init AI-Prod-Assistant

# Change directory to project
cd ai-prod-assistant

# Open the project in VS Code
code .


# Check installed packages in uv
uv pip list

# List available Python versions in uv
uv python list

# Attempt to activate Python environment (note: 'activate' is not a uv subcommand)
uv activate cpython-3.10.18

# Attempt to upgrade pip/setuptools/wheel (fails without environment)
uv pip install --upgrade pip setuptools wheel

# Create a new uv virtual environment using Python 3.10.18
uv venv ai_prod --python cpython-3.10.18

# Activate the created environment
ai_prod\Scripts\activate
