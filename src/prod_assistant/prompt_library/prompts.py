from enum import Enum
from typing import Dict
import string


class PromptType(str, Enum):
    PRODUCT_BOT = "product_bot"
    # REVIEW_BOT = "review_bot"
    # COMPARISON_BOT = "comparison_bot"


class PromptTemplate:
    def __init__(self, template: str, description: str = "", version: str = "v1"):
        self.template = template.strip()
        self.description = description
        self.version = version

    def format(self, **kwargs) -> str:
        # Validate placeholders before formatting
        missing = [f for f in self.required_placeholders() if f not in kwargs]
        if missing:
            raise ValueError(f"Missing placeholders: {missing}")
        return self.template.format(**kwargs)

    def required_placeholders(self):
        return [
            field_name
            for _, field_name, _, _ in string.Formatter().parse(self.template)
            if field_name
        ]


# Central Registry
PROMPT_REGISTRY: Dict[PromptType, PromptTemplate] = {
    PromptType.PRODUCT_BOT: PromptTemplate(
        """
        You are an expert EcommerceBot specialized in product recommendations and handling customer queries.
        Analyze the provided product titles, ratings, and reviews to provide accurate, helpful responses.
        Stay relevant to the context, and keep your answers concise and informative.

        Response rules:
        1. Do not mention reviewer names, usernames, or personal identifiers.
        2. Summarize feedback as themes (for example: "good for sensitive skin", "minimal white cast", "light texture").
        3. If multiple reviews are present, consolidate them into clear bullet points.
        4. End with a short sentiment summary in this format:
           Sentiment: <Positive/Neutral/Mixed/Negative> (confidence: <low/medium/high>)
        5. If context is insufficient, say so clearly and avoid inventing details.

        CONTEXT:
        {context}

        QUESTION: {question}

        YOUR ANSWER:
        """,
        description="Handles ecommerce QnA & product recommendation flows",
    )
}
