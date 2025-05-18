"""TransactionAgent: Main agent logic for transaction normalization using LLMs.

This module defines the TransactionAgent class, which uses a language model (LLM) to parse and normalize bank transaction data. The agent takes raw transaction rows and produces structured Transaction objects, leveraging the LLM for reasoning and field extraction.
"""

import csv
import json
import re
from io import StringIO

from app.agents.prompts import SYSTEM_PROMPT, USER_PROMPT_LOG_LABEL, USER_PROMPT_TEMPLATE
from app.core.models import Transaction
from app.core.settings import Settings
from app.core.utils import get_logger

CSV_FIELD_COUNT = 5
MAX_PROMPT_LOG_LEN = 300
PROMPT_LOG_LEN = 80

logger = get_logger("bank-normalizer.agent")


def _get_color(color: str) -> str:
    try:
        from colorlog.escape_codes import escape_codes as _codes

        return _codes.get(color, "")
    except Exception:
        return ""


class TransactionAgent:
    """Agent responsible for reasoning and LLM-based normalization of transaction data."""

    def __init__(self, llm_client: object, settings: Settings) -> None:
        """Initialize the TransactionAgent with an LLM client and settings."""
        self.llm_client = llm_client
        self.settings = settings

    def parse_transaction(
        self,
        row: dict,
        categories: list[str],
        payees: list[str],
        row_index: int | None = None,
        total_rows: int | None = None,
    ) -> Transaction:
        """Use the LLM to parse and normalize a transaction row."""
        row_info = f"[AI ROW {row_index}/{total_rows}] " if row_index and total_rows else ""
        cyan = _get_color("cyan")
        green = _get_color("green")
        yellow = _get_color("yellow")
        reset = _get_color("reset")
        logger.info(f"{cyan}{row_info}INPUT: {row}{reset}")
        logger.info(f"{yellow}{row_info}PROMPT: {USER_PROMPT_LOG_LABEL}{reset}")
        payload = {k: (v.isoformat() if hasattr(v, "isoformat") else str(v)) for k, v in row.items()}
        payload["existing_categories"] = categories
        payload["existing_payees"] = payees
        system_msg = {"role": "system", "content": SYSTEM_PROMPT}
        user_prompt = USER_PROMPT_TEMPLATE.format(payload=json.dumps(payload))
        user_msg = {"role": "user", "content": user_prompt}
        try:
            logger.info(f"{yellow}{row_info}AGENT: Calling LLM...{reset}")
            completion = self.llm_client.chat.completions.create(
                model=self.settings.deepseek_model,
                messages=[system_msg, user_msg],
                temperature=self.settings.deepseek_temperature,
                max_completion_tokens=self.settings.deepseek_max_completion_tokens,
                top_p=self.settings.deepseek_top_p,
                stream=self.settings.deepseek_stream,
                stop=self.settings.deepseek_stop,
            )
        except Exception as exc:
            msg = f"Groq API call failed: {exc}"
            logger.exception(msg, exc_info=True)
            raise RuntimeError(msg) from exc
        raw_output = self._collect_llm_output(completion)
        logger.info(f"{green}{row_info}OUTPUT: {raw_output}{reset}")
        data = self._extract_and_normalize_json(raw_output, row_info, yellow, reset)
        if data:
            logger.info(f"{green}{row_info}AGENT: Normalized transaction: {data}{reset}")
            return Transaction(**data)
        # fallback: CSV row extraction (legacy)
        return self._parse_csv_fallback(raw_output)

    def _collect_llm_output(self, completion: object) -> str:
        """Collect the full output from the LLM completion stream."""
        raw_output = ""
        try:
            for chunk in completion:
                text = chunk.choices[0].delta.content or ""
                raw_output += text
        except Exception as exc:
            msg = f"Groq streaming error: {exc}"
            logger.exception(msg)
            raise RuntimeError(msg) from exc
        return raw_output

    def _extract_and_normalize_json(self, raw_output: str, row_info: str, yellow: str, reset: str) -> dict | None:
        """Extract and normalize the first valid JSON object from the LLM output."""
        json_matches = list(re.finditer(r"\{.*?\}", raw_output, re.DOTALL))
        if not json_matches:
            return None
        for match in json_matches:
            json_str = match.group(0)
            try:
                logger.info(f"{yellow}{row_info}AGENT: Parsing JSON...{reset}")
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning(f"{row_info}Failed to parse JSON: {e}")
                continue
            required_fields = ["date", "payee", "notes", "category", "amount"]
            for field in required_fields:
                if field not in data:
                    msg = f"Missing field '{field}' in LLM JSON output: {data}"
                    logger.exception(f"{yellow}{row_info}AGENT: {msg}{reset}")
                    raise ValueError(msg) from None
            data["notes"] = data["notes"] if data["notes"] is not None else ""
            data["category"] = data["category"] if data["category"] is not None else ""
            try:
                data["amount"] = float(data["amount"])
            except Exception as exc:
                msg = f"Could not convert 'amount' to float: {data['amount']} ({exc})"
                logger.exception(f"{yellow}{row_info}AGENT: {msg}{reset}")
                raise ValueError(msg) from exc
            return data
        return None

    def _parse_csv_fallback(self, raw_output: str) -> Transaction:
        """Fallback: parse the last non-empty line as a CSV row."""
        lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
        if not lines:
            msg = "No non-empty lines in LLM output."
            logger.exception(msg)
            raise ValueError(msg) from None
        csv_row = lines[-1]
        logger.info(f"Extracted CSV row: {csv_row}")
        try:
            reader = csv.reader(StringIO(csv_row))
            fields = next(reader)
        except Exception as exc:
            msg = f"Failed to parse CSV row: {exc}"
            logger.exception(msg)
            raise ValueError(msg) from exc
        if len(fields) != CSV_FIELD_COUNT:
            msg = f"Expected {CSV_FIELD_COUNT} fields in CSV row, got {len(fields)}: {fields}"
            logger.exception(msg)
            raise ValueError(msg) from None
        data = {
            "date": fields[0],
            "payee": fields[1],
            "notes": fields[2],
            "category": fields[3],
            "amount": float(fields[4]),
        }
        logger.info(f"Normalized transaction: {data}")
        return Transaction(**data)
