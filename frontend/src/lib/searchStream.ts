import axios from "axios";
import type { SearchResponse } from "./types";
import { LIVE_TIMEOUT_MS, serviceError } from "./liveService";

export class AnswerStream {
  private offset = 0;
  private buffer = "";
  private done = false;
  private failed = false;
  receivedSources = false;
  value: SearchResponse = { summary: "", results: [] };
  constructor(private update: (value: SearchResponse) => void) {}
  consume(fullText: string) {
    if (fullText.length > 1_000_000) throw new Error("Answer stream too large");
    this.buffer += fullText.slice(this.offset);
    this.offset = fullText.length;
    let boundary;
    while ((boundary = this.buffer.indexOf("\n\n")) >= 0) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const line = block.split("\n").find((line) => line.startsWith("data: "));
      if (!line) continue;
      const data = JSON.parse(line.slice(6));
      if (this.done || this.failed) continue;
      if (
        data.type === "sources" &&
        Array.isArray(data.results) &&
        !this.receivedSources
      ) {
        this.receivedSources = true;
        this.value = {
          summary: "",
          results: data.results,
          retrieval_notice:
            typeof data.retrieval_notice === "string"
              ? data.retrieval_notice
              : undefined,
        };
      } else if (
        data.type === "delta" &&
        typeof data.text === "string" &&
        this.receivedSources
      )
        this.value = {
          ...this.value,
          summary: (this.value.summary || "") + data.text,
        };
      else if (data.type === "done") this.done = true;
      else if (data.type === "error") {
        this.failed = true;
        this.value = {
          ...this.value,
          summary: null,
          answer_status: "unavailable",
          error: {
            message:
              typeof data.message === "string"
                ? data.message
                : "The answer was interrupted. Please try again.",
          },
        };
      } else throw new Error("Invalid answer stream");
      this.update({ ...this.value });
    }
  }
  finish(): SearchResponse {
    if (this.failed) return this.value;
    if (!this.done || !this.receivedSources || !this.value.summary?.trim())
      return {
        ...this.value,
        summary: null,
        answer_status: "unavailable",
        error: { message: "The answer was interrupted. Please try again." },
      };
    return this.value;
  }
}

export async function searchWithStream(
  base: string,
  query: string,
  signal: AbortSignal,
  update: (value: SearchResponse) => void,
): Promise<SearchResponse> {
  const parser = new AnswerStream((value) => {
    if (!signal.aborted) update(value);
  });
  let progressError: Error | null = null;
  try {
    const response = await axios.post<string | SearchResponse>(
      `${base}/search`,
      { query },
      {
        timeout: LIVE_TIMEOUT_MS,
        signal,
        responseType: "text",
        headers: { Accept: "text/event-stream" },
        onDownloadProgress: (event) => {
          // The browser XHR adapter exposes text received so far. No simulated typing.
          const target = event.event?.target as XMLHttpRequest | null;
          if (
            typeof target?.responseText === "string" &&
            target.responseText.startsWith("data: ") &&
            !progressError
          ) {
            try {
              parser.consume(target.responseText);
            } catch {
              progressError = new Error("Invalid answer stream");
            }
          }
        },
      },
    );
    if (progressError) throw progressError;
    if (typeof response.data !== "string") return response.data; // Compatible JSON API clients/tests.
    if (response.data.trimStart().startsWith("{"))
      return JSON.parse(response.data); // Older backend rollout.
    parser.consume(response.data);
    return parser.finish();
  } catch (error) {
    if (signal.aborted) throw { code: "ERR_CANCELED" };
    const transport = error as { response?: { data?: unknown } };
    if (typeof transport.response?.data === "string") {
      try {
        transport.response.data = JSON.parse(transport.response.data);
      } catch {
        /* Non-JSON gateway error. */
      }
    }
    if (parser.receivedSources)
      return {
        ...parser.value,
        summary: null,
        answer_status: "unavailable",
        error: { message: serviceError(error) },
      };
    throw error;
  }
}
