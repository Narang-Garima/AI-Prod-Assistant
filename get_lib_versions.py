import importlib.metadata
packages = ['langchain', 'langchain_core', 'python-dotenv', 'langgraph', 'streamlit']
for package in packages:
    try:
        version = importlib.metadata.version(package)
        print(f"{package} version: {version}")
    except importlib.metadata.PackageNotFoundError:
        print(f"{package} not found")
