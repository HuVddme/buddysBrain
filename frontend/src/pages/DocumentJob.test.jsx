import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import DocumentJob from './DocumentJob';
import SubmitDocument from './SubmitDocument';

vi.mock('axios', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock('react-confetti', () => ({ default: () => null }));
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

test('link submissions send only fields accepted by the validated API', async () => {
  axios.post.mockRejectedValue({ response: { status: 503, data: { detail: 'Service unavailable' } } });
  render(<MemoryRouter><SubmitDocument /></MemoryRouter>);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Title:'), 'Heaps');
  await user.selectOptions(screen.getByLabelText('Media Type:'), 'article');
  await user.type(screen.getByLabelText('Article URL:'), 'https://example.com/heaps');
  await user.type(screen.getByLabelText('Course Name:'), 'CS101');
  await user.type(screen.getByLabelText('Description:'), 'Study notes');
  await user.click(screen.getByRole('button', { name: 'Submit' }));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Service unavailable');
  expect(axios.post).toHaveBeenCalledWith('/api/resources', {
    title: 'Heaps', media_type: 'article', media_link: 'https://example.com/heaps',
    course: 'CS101', description: 'Study notes',
  }, { timeout: 90000 });
});

test('accepted upload shows waiting status rather than success', async () => {
  axios.get.mockResolvedValue({ data: job });
  show();
  expect(await screen.findByText('Upload saved — waiting to process')).toBeTruthy();
  expect(screen.queryByText('Document added to the library')).toBeNull();
  await waitFor(() => expect(axios.get).toHaveBeenCalledOnce());
});

test.each([false, true])('completed upload uses the saved title and live link (duplicate=%s)', async duplicate => {
  axios.post.mockResolvedValue({ data: { _id: 'saved-id', title: 'Original saved title', duplicate } });
  const user = userEvent.setup();
  render(<MemoryRouter><SubmitDocument /></MemoryRouter>);
  await user.type(screen.getByLabelText('Title:'), 'A newly typed title');
  await user.selectOptions(screen.getByLabelText('Media Type:'), 'document');
  await user.upload(screen.getByLabelText('Document:'), new File(['notes'], 'notes.txt', { type: 'text/plain' }));
  await user.type(screen.getByLabelText('Course Name:'), 'CS101');
  await user.type(screen.getByLabelText('Description:'), 'Notes');
  await user.click(screen.getByRole('button', { name: 'Submit' }));
  expect(await screen.findByRole('heading', { name: duplicate ? 'Already in the library' : 'Resource saved' })).toBeTruthy();
  expect(screen.getByText('"Original saved title" is in the library.')).toBeTruthy();
  expect(screen.queryByText(/being processed/)).toBeNull();
  expect(screen.getByRole('link', { name: 'Ask Buddy' }).getAttribute('href')).toBe('/ask?mode=live');
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

test('a bookmarked job status opens without uploading again', async () => {
  axios.get.mockResolvedValue({ data: { ...job, status: 'succeeded' } });
  render(<MemoryRouter initialEntries={[`/submit?job=${job.job_id}`]}><SubmitDocument /></MemoryRouter>);
  expect(await screen.findByText('Document added to the library')).toBeTruthy();
  expect(axios.post).not.toHaveBeenCalled();
});
