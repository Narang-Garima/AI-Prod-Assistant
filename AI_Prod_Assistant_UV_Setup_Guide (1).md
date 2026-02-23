# AI-Prod-Assistant --- UV Environment & Project Setup Guide

*Last Updated: 2026-02-20*

------------------------------------------------------------------------

## 📁 Recommended Project Structure (src layout)

    AI-Prod-Assistant/
    │
    ├── src/
    │   └── prod_assistant/
    │       ├── config/
    │       ├── etl/
    │       ├── evaluation/
    │       ├── exception/
    │       ├── logger/
    │       ├── prompt_library/
    │       ├── retriever/
    │       ├── utils/
    │       ├── workflow/
    │       └── __init__.py
    │
    ├── data/
    ├── logs/
    ├── notebook/
    ├── static/
    ├── templates/
    ├── test/
    ├── venv/
    │
    ├── main.py
    ├── requirements.txt
    ├── pyproject.toml
    └── README.md

------------------------------------------------------------------------

# 🔧 Why We Use `src/` Layout

-   Prevents setuptools from picking up non-code folders like `data/`,
    `logs/`, `templates`
-   Clean package discovery
-   Works properly with `uv pip install -e .`
-   No import changes required in code

Imports stay like:

``` python
from prod_assistant.etl import some_function
```

------------------------------------------------------------------------

# 📦 pyproject.toml (Correct Configuration)

``` toml
[project]
name = "ai-prod-assistant"
version = "0.1.0"
description = "AI Production Assistant"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.129.0",
    "playwright",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.uv.workspace]
members = ["AI-Prod-Assistant"]
```

------------------------------------------------------------------------

# 📜 requirements.txt Guidelines

-   Avoid duplicate packages
-   Do not define two versions of the same package
-   Keep pinned versions only when necessary

Example:

    beautifulsoup4==4.13.5
    uvicorn==0.35.0
    requests
    jinja2==3.1.6
    streamlit==1.49.1
    selenium==4.35.0
    playwright==1.35.0
    python-dotenv==1.1.1
    structlog==25.4.0

------------------------------------------------------------------------

# 🚀 Full Fresh Setup Using UV

## 1️⃣ Remove old environment (if needed)

    deactivate
    rmdir /s /q venv

------------------------------------------------------------------------

## 2️⃣ Create Virtual Environment

    uv venv venv --python cpython-3.10.18
    venv\Scripts\activate

------------------------------------------------------------------------

## 3️⃣ Install Project in Editable Mode

    uv pip install -e .

This makes `prod_assistant` importable everywhere.

------------------------------------------------------------------------

## 4️⃣ Install All Dependencies

    uv pip install -r requirements.txt

------------------------------------------------------------------------

## 5️⃣ Install Playwright Browsers

    playwright install

------------------------------------------------------------------------

# ▶ Running the Project

Always run from project root:

    (venv) C:\Users\<your-username>\AI-Prod-Assistant>

### FastAPI

    uvicorn main:app --reload

### Streamlit

    streamlit run scrapper_ui.py

### Module execution

    python -m prod_assistant.some_module

------------------------------------------------------------------------

# 🛑 Common Errors & Fixes

### 1. Multiple top-level packages discovered

Fix: Use `src/` layout and configure:

    [tool.setuptools.packages.find]
    where = ["src"]

------------------------------------------------------------------------

### 2. Dependency conflict (FastAPI version mismatch)

Ensure: - `pyproject.toml` and `requirements.txt` do not conflict - Do
not pin incompatible versions

------------------------------------------------------------------------

### 3. ModuleNotFoundError: prod_assistant

Fix:

    uv pip install -e .

------------------------------------------------------------------------

### 4. Playwright not launching browser

Run:

    playwright install

------------------------------------------------------------------------

# 📌 Best Practices Going Forward

-   Always activate venv before running anything
-   Always run from project root
-   Use `-e .` for development installs
-   Keep Python code inside `src/`
-   Keep data/logs/templates outside `src/`
-   Avoid mixing conda and uv environments
-   Never duplicate dependency versions

------------------------------------------------------------------------

# 🧠 Mental Model

`pyproject.toml` → Defines the project\
`requirements.txt` → Defines additional pinned dependencies\
`uv venv` → Creates environment\
`uv pip install -e .` → Registers your package\
`uv pip install -r requirements.txt` → Installs dependencies\
`playwright install` → Installs browser binaries

------------------------------------------------------------------------

# ✅ Final Verified Setup Order

    uv venv venv --python cpython-3.10.18
    venv\Scripts\activate
    uv pip install -e .
    uv pip install -r requirements.txt
    playwright install

You are now fully production-ready.
