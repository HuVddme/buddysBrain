import { useEffect, useState } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { serviceError } from '../lib/liveService';

const labels = {
  queued: 'Upload saved — waiting to process',
  processing: 'Processing your document',
  retrying: 'Waiting to retry processing',
  succeeded: 'Document added to the library',
  failed: 'Document processing failed',
  cancelled: 'This document was removed',
};
const pending = ['queued', 'processing', 'retrying'];

export default function DocumentJob({ initialJob, apiBase, onNewUpload }) {
  const [job, setJob] = useState(initialJob);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    let timer;
    async function poll() {
      try {
        const { data } = await axios.get(`${apiBase}/ingestion/${initialJob.job_id}`, {
          timeout: 15000, signal: abort.signal,
        });
        if (abort.signal.aborted) return;
        setJob(data);
        setError('');
        if (pending.includes(data.status)) timer = setTimeout(poll, 4000);
      } catch (err) {
        if (!abort.signal.aborted) setError(serviceError(err));
      }
    }
    poll();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [apiBase, initialJob.job_id, refresh]);

  async function retry() {
    if (retrying) return;
    setRetrying(true);
    setError('');
    try {
      const { data } = await axios.post(`${apiBase}/ingestion/${job.job_id}/retry`, {}, { timeout: 20000 });
      setJob(data);
      setRefresh(value => value + 1);
    } catch (err) {
      setError(serviceError(err));
    } finally {
      setRetrying(false);
    }
  }

  return (
    <section className="content" aria-label="Document processing status">
      <h1>{job.title || 'Your document'}</h1>
      <p role="status" aria-live="polite">{labels[job.status] || 'Checking processing status…'}</p>
      {initialJob.duplicate && <p>This file was already submitted. We’re showing its existing processing result.</p>}
      {pending.includes(job.status) && <p>Your upload is saved. You can leave this page and return in this tab to check progress.</p>}
      {job.dispatch_pending && <p>Processing has not started yet. Your saved upload is safe.</p>}
      {job.error && <p role="alert">{job.error.message}</p>}
      {error && <p role="alert">{error}</p>}
      {job.retry_available && <button type="button" disabled={retrying} onClick={retry}>
        {retrying ? 'Requesting retry…' : 'Retry processing'}
      </button>}
      {(error || job.status !== 'succeeded') && <button type="button" onClick={() => setRefresh(value => value + 1)}>Refresh status</button>}
      {job.status === 'succeeded' && <>
        <p>The document and its passages are saved. Search indexing may take a short time to catch up.</p>
        <Link to="/ask?mode=live">Ask about your document</Link>
      </>}
      <p><button type="button" onClick={onNewUpload}>Submit another resource</button></p>
    </section>
  );
}
