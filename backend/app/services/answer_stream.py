"""Real provider deltas; no artificial typing delay or background request replay."""
import asyncio
import json
import logging
import os
from contextlib import aclosing

from openai import AsyncOpenAI, AuthenticationError, PermissionDeniedError, RateLimitError, APITimeoutError
from .ai import completion_options
from .answers import answer_messages, MAX_OUTPUT_TOKENS
from .processing import ProcessingError


async def answer_deltas(results, question):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise ProcessingError("Live AI access needs attention from the site owner. The demo is still available.")
    # Context managers close both the response and HTTP client on errors or cancellation.
    async with AsyncOpenAI(api_key=key, timeout=30.0, max_retries=1) as client:
        stream = await client.chat.completions.create(
            **completion_options(answer_messages(results, question), MAX_OUTPUT_TOKENS), stream=True)
        finished, has_text = False, False
        async with stream:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.delta.refusal:
                    raise ProcessingError("Buddy could not complete this answer. Try rephrasing your question.")
                if choice.delta.content:
                    has_text = has_text or bool(choice.delta.content.strip())
                    yield choice.delta.content
                if choice.finish_reason is not None:
                    if choice.finish_reason != "stop":
                        raise ProcessingError("The answer stopped before it was complete. Try a shorter question.")
                    finished = True
        if not finished or not has_text:
            raise ProcessingError("The answer was interrupted. Please try again.")


def event(kind, **values):
    return "data: " + json.dumps({"type": kind, **values}, ensure_ascii=False) + "\n\n"


async def search_events(results, question, extra):
    yield event("sources", results=results, **extra)
    try:
        async with asyncio.timeout(65):
            async with aclosing(answer_deltas(results, question)) as deltas:
                async for text in deltas:
                    yield event("delta", text=text)
        yield event("done")
    except asyncio.CancelledError:
        # StreamingResponse cancels this generator when the browser disconnects.
        raise
    except Exception as exc:
        logging.getLogger(__name__).warning("Answer stream failed (%s)", type(exc).__name__)
        if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
            message = "Live AI access needs attention from the site owner. The demo is still available."
        elif isinstance(exc, RateLimitError):
            message = "The AI service has reached its usage allowance. Try again later or explore the demo."
        elif isinstance(exc, (APITimeoutError, TimeoutError)):
            message = "The AI service took too long. Please try again."
        elif isinstance(exc, ProcessingError):
            message = str(exc)
        else:
            message = "The AI answer was interrupted. Please try again."
        # Never mark a truncated response as successful; keep sources available.
        yield event("error", code="ai_unavailable", message=message)
