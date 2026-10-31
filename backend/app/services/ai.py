"""Shared Chat Completions requests for text and image summarization."""
import os

from .processing import ProcessingError, get_ai_client


DEFAULT_MODEL = "gpt-6-luna"
REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
# Application text-size budget, not an exact model token count. This avoids
# relying on a tokenizer mapping that does not yet recognize GPT-6 Luna.
MAX_INPUT_TEXT_BYTES = 400_000


def validate_text_size(text: str) -> None:
    if len(text.encode("utf-8")) > MAX_INPUT_TEXT_BYTES:
        raise ProcessingError("The input contains too much text to process (400 KB maximum).", 413)


def completion_options(messages, max_output_tokens: int = 500) -> dict:
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip()
    effort = os.getenv("OPENAI_REASONING_EFFORT", "none").strip()
    if not model or effort not in REASONING_EFFORTS:
        raise ProcessingError("AI model settings are invalid. Contact the administrator.", 503)
    try:
        budget = int(os.getenv("OPENAI_MAX_COMPLETION_TOKENS", str(max_output_tokens)))
        if not 1 <= budget <= 128_000:
            raise ValueError
    except ValueError as exc:
        raise ProcessingError("AI output limit is invalid. Contact the administrator.", 503) from exc

    # Count the entire text prompt (including the question), excluding image
    # data URLs. Upload size limits bound those separately.
    text_parts = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            text_parts.append(content)
        else:
            text_parts.extend(part["text"] for part in content if part["type"] == "text")
    validate_text_size("\n".join(text_parts))

    options = {
        "model": model,
        "messages": messages,
        "reasoning_effort": effort,
        "max_completion_tokens": budget,
    }
    if effort == "none":
        options["temperature"] = 0.3
    return options


def generate_summary(messages, max_output_tokens: int = 500) -> str:
    response = get_ai_client().chat.completions.create(**completion_options(messages, max_output_tokens))
    if not response.choices:
        raise ProcessingError("AI returned no summary. Please try again.")
    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise ProcessingError("AI reached its output limit before finishing. Contact the administrator.")
    if choice.finish_reason != "stop" or choice.message.refusal:
        raise ProcessingError("AI could not summarize this content. Try another resource or question.")
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise ProcessingError("AI returned an empty summary. Please try again.")
    return content.strip()
