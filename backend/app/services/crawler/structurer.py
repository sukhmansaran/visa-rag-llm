"""
LLM Structurer for the Crawler Pipeline.

Uses the existing GeminiService to extract structured visa/program fields
from clean text content. Supports batch processing, schema validation,
and controlled vocabulary normalization.
"""

import json
import logging
import math
import re
from typing import Optional

from app.services.crawler.types import (
    DEGREE_LEVEL_VOCABULARY,
    VALID_CURRENCIES,
    TuitionFee,
)

logger = logging.getLogger(__name__)

_MAX_BATCH_SIZE = 50

_VISA_EXTRACTION_PROMPT = """Extract structured visa/immigration data from the following text.
Return a JSON object with these fields (use null for missing):
{
  "visa_type": "string",
  "country": "string",
  "processing_time": "string",
  "required_documents": ["string"],
  "fees": "string",
  "eligibility_criteria": "string",
  "deadlines": "string",
  "application_steps": ["string"],
  "contact_information": "string"
}
Return ONLY valid JSON, no markdown or explanation."""

_PROGRAM_EXTRACTION_PROMPT = """Extract structured academic program data from the following text.
Return a JSON object with these fields (use null for missing):
{
  "program_name": "string",
  "university_name": "string",
  "degree_level": "string (bachelor/master/phd/postgraduate_diploma/short_course/foundation/certificate)",
  "tuition_fee": "number or null",
  "tuition_currency": "string (USD/EUR/GBP/CAD/AUD/SGD) or null",
  "duration": "string or null",
  "intake_dates": ["string"] or null,
  "location_city": "string or null",
  "location_country": "string or null",
  "entry_requirements": "string or null",
  "language_of_instruction": "string or null",
  "application_deadline": "string or null",
  "scholarship_availability": true/false/null
}
Return ONLY valid JSON, no markdown or explanation."""

_VISA_REQUIRED_FIELDS = {"visa_type", "country"}
_PROGRAM_REQUIRED_FIELDS = {"program_name", "university_name", "degree_level"}

# Mapping of common degree level variations to controlled vocabulary
_DEGREE_LEVEL_MAP: dict[str, str] = {
    "bachelor": "bachelor", "bachelors": "bachelor", "bachelor's": "bachelor",
    "bsc": "bachelor", "ba": "bachelor", "beng": "bachelor", "undergraduate": "bachelor",
    "master": "master", "masters": "master", "master's": "master",
    "msc": "master", "ma": "master", "mba": "master", "meng": "master",
    "postgraduate": "master", "graduate": "master",
    "phd": "phd", "doctorate": "phd", "doctoral": "phd", "dphil": "phd",
    "postgraduate diploma": "postgraduate_diploma", "pgdip": "postgraduate_diploma",
    "postgraduate_diploma": "postgraduate_diploma",
    "short course": "short_course", "short_course": "short_course",
    "mooc": "short_course", "online course": "short_course",
    "foundation": "foundation", "foundation year": "foundation",
    "certificate": "certificate", "cert": "certificate",
    "diploma": "certificate",
}


class LLMStructurer:
    """Extracts structured visa/program data from text using the local LLM."""

    def __init__(self, gemini_service=None):
        if gemini_service is None:
            from app.services.llm import llm_service as default_svc
            self.gemini = default_svc
        else:
            self.gemini = gemini_service

    async def extract_visa_fields(self, text: str) -> Optional[dict]:
        """Extract visa/immigration structured fields from text."""
        return await self._extract_with_retry(
            text, _VISA_EXTRACTION_PROMPT, "visa"
        )

    async def extract_program_fields(
        self, text: str, portal_name: Optional[str] = None
    ) -> Optional[dict]:
        """Extract academic program structured fields from text."""
        prompt = _PROGRAM_EXTRACTION_PROMPT
        if portal_name:
            prompt += f"\nThis text is from the {portal_name} portal."

        result = await self._extract_with_retry(text, prompt, "program")
        if result:
            if "degree_level" in result and result["degree_level"]:
                result["degree_level"] = self._normalize_degree_level(
                    result["degree_level"]
                )
            if "tuition_fee" in result and result["tuition_fee"] is not None:
                validated = self._validate_tuition(
                    str(result["tuition_fee"]),
                    result.get("tuition_currency"),
                )
                if validated:
                    result["tuition_fee"] = validated.amount
                    result["tuition_currency"] = validated.currency
                else:
                    result["tuition_fee"] = None
                    result["tuition_currency"] = None
        return result

    async def extract_batch(
        self, items: list[dict], batch_size: int = _MAX_BATCH_SIZE
    ) -> list[dict]:
        """Process multiple documents in batches of up to 50."""
        results: list[dict] = []
        num_batches = math.ceil(len(items) / batch_size)

        for i in range(num_batches):
            batch = items[i * batch_size : (i + 1) * batch_size]
            for item in batch:
                text = item.get("text", "")
                item_type = item.get("type", "visa")
                try:
                    if item_type == "program":
                        extracted = await self.extract_program_fields(
                            text, item.get("portal_name")
                        )
                    else:
                        extracted = await self.extract_visa_fields(text)
                    results.append(
                        {"source": item, "result": extracted, "success": extracted is not None}
                    )
                except Exception as e:
                    logger.error("Batch extraction failed for item: %s", e)
                    results.append({"source": item, "result": None, "success": False})

        return results

    async def _extract_with_retry(
        self, text: str, system_prompt: str, schema_type: str, max_retries: int = 2
    ) -> Optional[dict]:
        """Call Gemini and validate output, retrying on schema failure."""
        for attempt in range(max_retries + 1):
            try:
                response = await self.gemini.generate_answer(
                    system_prompt=system_prompt,
                    user_prompt=text,
                    temperature=0.1,
                    max_tokens=2000,
                )
                parsed = self._parse_json_response(response)
                if parsed and self._validate_schema(parsed, schema_type):
                    return parsed
                logger.warning(
                    "Schema validation failed (attempt %d/%d)",
                    attempt + 1, max_retries + 1,
                )
            except Exception as e:
                logger.warning(
                    "LLM extraction attempt %d failed: %s", attempt + 1, e
                )

        # All retries exhausted — flag for review
        logger.error("All LLM extraction retries exhausted, flagging for review")
        return None

    def _parse_json_response(self, response: str) -> Optional[dict]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = response.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the response
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return None

    def _validate_schema(self, data: dict, schema_type: str) -> bool:
        """Validate extracted JSON against predefined schema."""
        required = (
            _PROGRAM_REQUIRED_FIELDS if schema_type == "program"
            else _VISA_REQUIRED_FIELDS
        )
        for field in required:
            if field not in data or not data[field]:
                return False
        return True

    def _normalize_degree_level(self, raw: str) -> str:
        """Normalize to controlled vocabulary."""
        key = raw.strip().lower()
        normalized = _DEGREE_LEVEL_MAP.get(key)
        if normalized:
            return normalized
        # Fuzzy match: check if any key is contained in the raw string
        for k, v in _DEGREE_LEVEL_MAP.items():
            if k in key:
                return v
        # Default — return as-is but log warning
        if key not in DEGREE_LEVEL_VOCABULARY:
            logger.warning("Unknown degree level: %s", raw)
        return key

    def _validate_tuition(
        self, value: str, currency: Optional[str] = None
    ) -> Optional[TuitionFee]:
        """Parse and validate tuition as numeric + currency code."""
        try:
            # Strip currency symbols and commas
            cleaned = re.sub(r"[^\d.]", "", value)
            if not cleaned:
                return None
            amount = float(cleaned)
            if amount < 0:
                return None
            curr = (currency or "USD").upper().strip()
            if curr not in VALID_CURRENCIES:
                curr = "USD"
            return TuitionFee(amount=amount, currency=curr)
        except (ValueError, TypeError):
            return None
