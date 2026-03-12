from langchain_core.messages import AIMessage, HumanMessage

from prod_assistant.workflow.agentic_workflow_with_mcp_websearch import AgenticRAG


def _build_agent():
    agent = AgenticRAG.__new__(AgenticRAG)
    agent.max_rewrites = 2
    return agent


def test_latest_human_query_picks_last_user_message():
    agent = _build_agent()
    messages = [
        HumanMessage(content="first"),
        AIMessage(content="bot reply"),
        HumanMessage(content="second"),
    ]
    assert agent._latest_human_query(messages) == "second"


def test_ai_assistant_routes_greeting_to_direct():
    agent = _build_agent()
    state = {"messages": [HumanMessage(content="hi")]}
    result = agent._ai_assistant(state)
    assert result["last_route"] == "direct"
    assert "Hello!" in result["messages"][0].content


def test_ai_assistant_routes_memory_intent():
    agent = _build_agent()
    state = {"messages": [HumanMessage(content="what did i ask previously")]}
    result = agent._ai_assistant(state)
    assert result["last_route"] == "memory"
    assert result["messages"][0].content == "TOOL: memory"


def test_ai_assistant_routes_regular_query_to_retriever():
    agent = _build_agent()
    state = {"messages": [HumanMessage(content="price of google pixel 10")]}
    result = agent._ai_assistant(state)
    assert result["last_route"] == "retriever"
    assert result["messages"][0].content == "TOOL: retriever"


def test_grade_documents_goes_websearch_when_no_local():
    agent = _build_agent()
    state = {
        "messages": [
            HumanMessage(content="price of google pixel 10"),
            AIMessage(content="No local results found."),
        ],
        "rewrite_count": 0,
    }
    assert agent._grade_documents(state) == "websearch"


def test_grade_documents_goes_websearch_on_rewrite_limit():
    agent = _build_agent()
    state = {
        "messages": [
            HumanMessage(content="price of google pixel 10"),
            AIMessage(content="some docs"),
        ],
        "rewrite_count": 2,
    }
    assert agent._grade_documents(state) == "websearch"

