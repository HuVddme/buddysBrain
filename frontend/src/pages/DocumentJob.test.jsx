import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import DocumentJob from './DocumentJob';
import SubmitDocument from './SubmitDocument';

vi.mock('axios', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const job = { job_id: 'bbad0267-68bc-4f52-a777-4b1e8731ed96', title: 'Notes', status: 'queued', retry_available: false };

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv('VITE_ENABLE_LIVE', 'true');
  vi.stubEnv('VITE_API_BASE_URL', '/api');
  sessionStorage.clear();
});
afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

function show(initial = job) {
  render(<MemoryRouter><DocumentJob initialJob={initial} apiBase="/api" onNewUpload={vi.fn()} /></MemoryRouter>);
}

test('accepted upload shows waiting status rather than success', async () => {
  axios.get.mockResolvedValue({ data: job });
  show();
  expect(await screen.findByText('Upload saved — waiting to process')).toBeTruthy();
  expect(screen.queryByText('Document added to the library')).toBeNull();
  await waitFor(() => expect(axios.get).toHaveBeenCalledOnce());
});

test('failed job retries the saved upload without uploading its file again', async () => {
  const failed = { ...job, status: 'failed', retry_available: true, error: { message: 'AI unavailable' } };
  axios.get.mockResolvedValueOnce({ data: failed }).mockResolvedValue({ data: { ...job, status: 'succeeded' } });
  axios.post.mockResolvedValue({ data: job });
  show(failed);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Retry processing' }));
  expect(axios.post).toHaveBeenCalledWith(`/api/ingestion/${job.job_id}/retry`, {}, { timeout: 20000 });
  expect(await screen.findByText('Document added to the library')).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Ask about your document' }).getAttribute('href')).toBe('/ask?mode=live');
});

test('polling failure preserves the job and offers a status refresh', async () => {
  axios.get.mockRejectedValueOnce(new Error('Network')).mockResolvedValue({ data: { ...job, status: 'succeeded' } });
  show();
  const user = userEvent.setup();
  await screen.findByRole('alert');
  await user.click(screen.getByRole('button', { name: 'Refresh status' }));
  expect(await screen.findByText('Document added to the library')).toBeTruthy();
});

test('returning to the upload page resumes the saved job in this tab', async () => {
  sessionStorage.setItem('document-job', JSON.stringify({ apiBase: '/api', job: { job_id: job.job_id } }));
  axios.get.mockResolvedValue({ data: { ...job, status: 'succeeded' } });
  render(<MemoryRouter><SubmitDocument /></MemoryRouter>);
  expect(await screen.findByText('Document added to the library')).toBeTruthy();
  expect(axios.post).not.toHaveBeenCalled();
});

test('cancelled or permanent failures do not offer a retry', async () => {
  const failed = { ...job, status: 'failed', error: { message: 'No readable text' } };
  axios.get.mockResolvedValue({ data: failed });
  show(failed);
  expect(await screen.findByText('No readable text')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Retry processing' })).toBeNull();
});
