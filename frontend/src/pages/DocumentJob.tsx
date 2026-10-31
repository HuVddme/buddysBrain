import { useEffect, useState, useRef } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import Buddy, { Celebration } from "../components/Buddy";
import { usePreferences } from "../components/preferences";
import type { IngestionJob } from "../lib/types";
import { serviceError } from "../lib/liveService";

const labels = {
  queued: "Upload saved — waiting to process",
  processing: "Processing your document",
  retrying: "Waiting to retry processing",
  succeeded: "Document added to the library",
  failed: "Document processing failed",
  cancelled: "This document was removed",
};
const pending = ["queued", "processing", "retrying"];

export default function DocumentJob({
  initialJob,
  apiBase,
  onNewUpload,
}: {
  initialJob: IngestionJob;
  apiBase: string;
  onNewUpload: () => void;
}) {
  const [job, setJob] = useState(initialJob);
  const { playCompletion } = usePreferences();
  const celebrated = useRef(initialJob.status === "succeeded");
  useEffect(() => {
    if (job.status === "succeeded" && !celebrated.current) {
      celebrated.current = true;
      playCompletion();
    }
  }, [job.status, playCompletion]);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const { data } = await axios.get<IngestionJob>(
          `${apiBase}/ingestion/${initialJob.job_id}`,
          {
            timeout: 15000,
            signal: abort.signal,
          },
        );
        if (abort.signal.aborted) return;
        setJob(data);
        setError("");
        if (pending.includes(data.status || "")) timer = setTimeout(poll, 4000);
      } catch (err) {
        if (!abort.signal.aborted) setError(serviceError(err));
      }
    }
    poll();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [apiBase, initialJob.job_id, refresh]);

  async function retry() {
    if (retrying) return;
    setRetrying(true);
    setError("");
    try {
      const { data } = await axios.post<IngestionJob>(
        `${apiBase}/ingestion/${job.job_id}/retry`,
        {},
        { timeout: 20000 },
      );
      setJob(data);
      setRefresh((value) => value + 1);
    } catch (err) {
      setError(serviceError(err));
    } finally {
      setRetrying(false);
    }
  }

  return (
    <section className="job-card" aria-label="Document processing status">
      <Buddy
        mood={
          job.status === "succeeded"
            ? "celebrating"
            : pending.includes(job.status || "")
              ? "thinking"
              : "curious"
        }
        size="hero"
      />
      {job.status === "succeeded" && <Celebration />}
      <p className="eyebrow">DOCUMENT PROGRESS</p>
      <h1>{job.title || "Your document"}</h1>
      <p role="status" aria-live="polite">
        {(job.status ? labels[job.status] : null) ||
          "Checking processing status…"}
      </p>
      {pending.includes(job.status || "") && (
        <div className="answer-skeleton" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      )}
      <ol className="job-steps" aria-label="Processing steps">
        <li data-complete="true">Saved</li>
        <li
          data-complete={
            job.status === "processing" || job.status === "succeeded"
          }
        >
          Processing
        </li>
        <li data-complete={job.status === "succeeded"}>Ready</li>
      </ol>
      {initialJob.duplicate && (
        <p>
          This file was already submitted. We’re showing its existing processing
          result.
        </p>
      )}
      {pending.includes(job.status || "") && (
        <p>Your upload is saved. Bookmark this page to check progress later.</p>
      )}
      {job.dispatch_pending && (
        <p>Processing has not started yet. Your saved upload is safe.</p>
      )}
      {job.error && <p role="alert">{job.error.message}</p>}
      {error && <p role="alert">{error}</p>}
      {job.retry_available && (
        <button
          className="btn btn-secondary"
          type="button"
          disabled={retrying}
          onClick={retry}
        >
          {retrying ? "Requesting retry…" : "Retry processing"}
        </button>
      )}
      {(error || job.status !== "succeeded") && (
        <button
          className="btn btn-secondary"
          type="button"
          onClick={() => setRefresh((value) => value + 1)}
        >
          Refresh status
        </button>
      )}
      {job.status === "succeeded" && (
        <>
          <p>
            The document and its passages are saved. Search indexing may take a
            short time to catch up.
          </p>
          <Link className="btn btn-primary" to="/ask?mode=live">
            Ask about your document
          </Link>
        </>
      )}
      <p>
        <button
          className="btn btn-secondary"
          type="button"
          onClick={onNewUpload}
        >
          Submit another resource
        </button>
      </p>
    </section>
  );
}
