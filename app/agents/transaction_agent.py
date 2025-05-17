"""TransactionAgent: Main agent logic for transaction normalization using LLMs.

This module defines the TransactionAgent class, which uses a language model (LLM) to parse and normalize bank transaction data. The agent takes raw transaction rows and produces structured Transaction objects, leveraging the LLM for reasoning and field extraction.
"""

import json

from groq import Groq

from app.core.models import Transaction
from app.core.settings import Settings


class TransactionAgent:
    """Agent responsible for reasoning and LLM-based normalization of transaction data."""

    def __init__(self, llm_client: Groq, settings: Settings) -> None:
        """Initialize the TransactionAgent with an LLM client and settings."""
        self.llm_client = llm_client
        self.settings = settings

    def parse_transaction(self, row: dict, categories: list[str], payees: list[str]) -> Transaction:
        """Use the LLM to parse and normalize a transaction row."""
        payload = dict(row)
        payload["existing_categories"] = categories
        payload["existing_payees"] = payees
        system_msg = {
            "role": "system",
            "content": (
                "Parse bank transaction data. Return ONLY a valid CSV row with the columns: "
                "date,payee,notes,category,amount. Do not include any explanations, thoughts, or extra text. "
                "Output must be a single CSV row."
            ),
        }
        user_msg = {"role": "user", "content": json.dumps(payload)}
        completion = self.llm_client.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=[system_msg, user_msg],
            temperature=self.settings.deepseek_temperature,
            max_completion_tokens=self.settings.deepseek_max_completion_tokens,
            top_p=self.settings.deepseek_top_p,
            stream=self.settings.deepseek_stream,
            stop=self.settings.deepseek_stop,
        )
        raw_output = ""
        for chunk in completion:
            text = chunk.choices[0].delta.content or ""
            raw_output += text
        data = json.loads(raw_output)
        for k in ("date", "payee", "notes", "amount"):
            msg = f"Missing {k} in AI response"
            if k not in data:
                raise ValueError(msg)
        data["category"] = data.get("category") or ""
        return Transaction(**data)
