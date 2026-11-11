"""One helper for every AI call: the model must fill a strict JSON form."""
import json
import logging
import time

from openai import BadRequestError, OpenAI

from . import config

logger = logging.getLogger("getpaid")


def structured_call(system: str, user: str, name: str, schema: dict, temperature: float = 0.0,
                    max_tokens: int = 1500):
    """Returns (data, model_name, latency_ms).

    Guards against a known structured-output failure: the model sometimes gets stuck repeating
    text until it hits its length limit, leaving cut-off JSON. We cap the length so that fails
    fast, and retry once at temperature 0.
    """
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is empty in your .env file.")
    # Never hang: give up after 45 seconds, retry once on network errors.
    client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=45.0, max_retries=1)
    started = time.perf_counter()
    last_error = None

    for attempt in (1, 2):
        request = dict(
            model=config.OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
            temperature=temperature if attempt == 1 else 0.0,
            max_tokens=max_tokens,
        )
        try:
            response = client.chat.completions.create(**request)
        except BadRequestError as error:
            text = str(error)
            if "temperature" in text:
                request.pop("temperature")
            if "max_tokens" in text:  # newer models call it max_completion_tokens
                request["max_completion_tokens"] = request.pop("max_tokens")
            if "temperature" not in text and "max_tokens" not in text:
                raise
            response = client.chat.completions.create(**request)

        choice = response.choices[0]
        message = choice.message
        if getattr(message, "refusal", None):
            raise RuntimeError(f"The AI refused: {message.refusal}")
        try:
            if choice.finish_reason == "length":
                raise ValueError("the answer was cut off at the length limit")
            data = json.loads(message.content)
        except (ValueError, TypeError) as error:
            last_error = error
            logger.warning("AI call %s attempt %d unusable (%s); %s", name, attempt, error,
                           "retrying" if attempt == 1 else "giving up")
            continue
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info("AI call %s finished in %d ms (attempt %d)", name, latency_ms, attempt)
        return data, response.model, latency_ms

    raise RuntimeError(f"The AI's answer was unusable twice ({last_error}).")
