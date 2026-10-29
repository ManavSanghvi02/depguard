"""The agent's answer: the arguments of its `submit_explanation` tool call, validated here.

There are no score, tier or fix-version fields: those are shown from stored data, never the LLM.
"""

from pydantic import BaseModel, ConfigDict, Field


class ExplanationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=400)
    why_it_matters: str = Field(min_length=1, max_length=700)
    what_to_do: str = Field(min_length=1, max_length=500)
    cited_ids: list[str] = Field(max_length=10)

    def text(self) -> str:
        return f"{self.summary}\n\n{self.why_it_matters}\n\n{self.what_to_do}"


# The same shape as a tool definition. Written out by hand because Gemini accepts only a subset of
# JSON Schema; the length limits are checked by the model above instead.
SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_explanation",
        "description": "Submit the final explanation. Call it once, after reading the facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One or two sentences: what is wrong.",
                },
                "why_it_matters": {
                    "type": "string",
                    "description": "Why it matters for this project, using only the given facts.",
                },
                "what_to_do": {"type": "string", "description": "The next step for the developer."},
                "cited_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The advisory IDs mentioned in the text.",
                },
            },
            "required": ["summary", "why_it_matters", "what_to_do", "cited_ids"],
        },
    },
}
