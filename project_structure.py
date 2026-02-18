import os

def create_project_structure(project_name):
    structure = {
        f"{project_name}/config": ["__init__.py", "config.yaml"],
        f"{project_name}/etl": ["__init__.py", "data_ingestion.py", "data_scrapper.py"],
        f"{project_name}/evaluation": ["__init__.py"],
        f"{project_name}/exception": ["__init__.py", "custom_exception.py"],
        f"{project_name}/logger": ["__init__.py", "custom_logger.py"],
        f"{project_name}/prompt_library": ["__init__.py"],
        f"{project_name}/retriever": ["__init__.py"],
        f"{project_name}/utils": ["__init__.py","config_loader.py", "model_loader.py"],
        f"{project_name}/workflow": ["__init__.py"],
        f"{project_name}": [".env"]
    }

    for folder, files in structure.items():
        os.makedirs(folder, exist_ok=True)
        for file in files:
            file_path = os.path.join(folder, file)
            with open(file_path, "w") as f:
                pass  # Create empty file
        print(f"Created folder: {folder} with files: {files}")

if __name__ == "__main__":
    create_project_structure("prod_assistant")
