"""One helper for every AI call: the model must fill a strict JSON form."""
import json
import time

from openai import BadRequestError, OpenAI

from . import config


def structured_call(system: str, user: str, name: str, schema: dict, temperature: float = 0.0):
    """Returns (data, model_name, latency_ms)."""
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is empty in your .env file.")
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    request = dict(
        model=config.OPENAI_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        temperature=temperature,
    )
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**request)
    except BadRequestError as error:
        if "temperature" not in str(error):
            raise
        request.pop("temperature")
        response = client.chat.completions.create(**request)
    latency_ms = int((time.perf_counter() - started) * 1000)
    message = response.choices[0].message
    if getattr(message, "refusal", None):
        raise RuntimeError(f"The AI refused: {message.refusal}")
    return json.loads(message.content), response.model, latency_ms
