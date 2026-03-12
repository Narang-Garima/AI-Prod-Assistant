from prod_assistant.prompt_library.prompts import PROMPT_REGISTRY, PromptType
from prod_assistant.utils.config_loader import load_config


def test_load_config_has_required_top_keys():
    config = load_config()
    required = {"astra_db", "embedding_model", "retriever", "llm", "agentic_rag"}
    assert required.issubset(config.keys())


def test_product_prompt_has_expected_placeholders():
    prompt = PROMPT_REGISTRY[PromptType.PRODUCT_BOT]
    placeholders = set(prompt.required_placeholders())
    assert placeholders == {"context", "question"}


def test_product_prompt_formats_successfully():
    prompt = PROMPT_REGISTRY[PromptType.PRODUCT_BOT]
    rendered = prompt.format(context="sample context", question="sample question")
    assert "CONTEXT:" in rendered
    assert "QUESTION:" in rendered
    assert "sample context" in rendered
    assert "sample question" in rendered

