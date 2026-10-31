import React from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import AskQuestion from './AskQuestion';
import SubmitDocument from './SubmitDocument';
import { lessons, lessonPassages } from '../demo/lessons';

vi.mock('axios', () => ({ default: { post: vi.fn() } }));

beforeEach(() => {
  vi.stubEnv('VITE_API_BASE_URL', '');
  vi.stubEnv('VITE_ENABLE_LIVE', 'false');
  vi.stubGlobal('SpeechRecognition', undefined);
  vi.stubGlobal('webkitSpeechRecognition', undefined);
  vi.stubGlobal('speechSynthesis', undefined);
});
afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function renderPage(Component = AskQuestion, path = '/ask') {
  render(<MemoryRouter initialEntries={[path]}>{React.createElement(Component)}</MemoryRouter>);
  return userEvent.setup();
}

test('all six saved answers have real sample passages and work without a service', async () => {
  const user = renderPage();
  expect(screen.getByText('Demo · saved examples')).toBeTruthy();
  expect(screen.queryByLabelText('Your question')).toBeNull();
  expect(screen.getByRole('button', { name: 'Ask live' }).disabled).toBe(true);
  for (const lesson of lessons) {
    await user.click(screen.getByRole('button', { name: `${lesson.course} ${lesson.title}` }));
    expect(screen.getByRole('link', { name: 'Download sample notes' }).getAttribute('download')).toBe(`${lesson.id}.txt`);
    for (const item of lesson.questions) {
      await user.click(screen.getByRole('button', { name: item.question }));
      expect(screen.getByText('Saved sample answer · not generated live')).toBeTruthy();
      expect(screen.getByText(item.answer)).toBeTruthy();
      for (const number of item.passages) {
        const passage = lessonPassages(lesson)[number - 1];
        expect(passage).toBeTruthy();
        expect(lesson.text.includes(passage)).toBe(true);
        expect(screen.getByText(passage, { selector: 'blockquote' })).toBeTruthy();
      }
    }
  }
  expect(axios.post).not.toHaveBeenCalled();
});

test('changing lessons clears the previous answer', async () => {
  const user = renderPage();
  await user.click(screen.getByRole('button', { name: lessons[0].questions[0].question }));
  await user.click(screen.getByRole('button', { name: 'CS201 Binary heaps' }));
  expect(screen.queryByText(lessons[0].questions[0].answer)).toBeNull();
});

test('an API URL alone never enables live requests', () => {
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
  renderPage(AskQuestion, '/ask?mode=live');
  expect(screen.getByRole('button', { name: 'Ask live' }).disabled).toBe(true);
  expect(axios.post).not.toHaveBeenCalled();
});

test('uploads explain the demo state instead of exposing a broken form', () => {
  renderPage(SubmitDocument, '/submit');
  expect(screen.getByRole('heading', { name: 'Uploads are not enabled yet' })).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Explore demo' }).getAttribute('href')).toBe('/ask');
  expect(screen.queryByRole('button', { name: 'Submit' })).toBeNull();
  expect(axios.post).not.toHaveBeenCalled();
});

test('explicit live mode preserves sources and question when AI generation fails', async () => {
  vi.stubEnv('VITE_ENABLE_LIVE', 'true');
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test/');
  axios.post.mockResolvedValue({ data: { summary: null, answer_status: 'unavailable',
    error: { message: 'AI processing timed out.' },
    results: [{ _id: 'r1', title: 'Saved limits lesson', summary: 'A saved resource summary.',
      media_type: 'document', media_link: 'https://example.com/limits.txt' }] } });
  const user = renderPage();
  await user.click(screen.getByRole('button', { name: 'Ask live' }));
  await user.type(screen.getByLabelText('Your question'), 'Explain limits{Enter}');
  expect(await screen.findByText('AI processing timed out. Retrieved sources are available below.')).toBeTruthy();
  expect(screen.getByText('A saved resource summary.')).toBeTruthy();
  expect(screen.getByLabelText('Your question').value).toBe('Explain limits');
  expect(screen.getByText('Saved summary · not an original passage')).toBeTruthy();
  expect(axios.post.mock.calls[0][0]).toBe('https://api.example.test/search');
});

test('original passages and page citations remain readable when AI fails', async () => {
  vi.stubEnv('VITE_ENABLE_LIVE', 'true');
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
  const text = 'Cedar can search course notes and use a calculator. It cannot delete documents.';
  axios.post.mockResolvedValue({ data: { summary: null, answer_status: 'unavailable',
    error: { message: 'AI processing timed out.' },
    results: [{ _id: 'r1', title: 'Cedar design', summary: 'An AI lesson.',
      media_type: 'document', media_link: 'https://example.com/cedar.pdf',
      passages: [{ citation: 'P1', page: 2, ordinal: 3, text }] }] } });
  const user = renderPage(AskQuestion, '/ask?mode=live');
  await user.type(screen.getByLabelText('Your question'), 'Can Cedar delete documents?{Enter}');
  expect(await screen.findByText(text, { selector: 'blockquote' })).toBeTruthy();
  expect(screen.getByText('[P1] Original document passage · Page 2')).toBeTruthy();
  expect(screen.queryByText('Saved summary · not an original passage')).toBeNull();
  expect(screen.queryByText('An AI lesson.')).toBeNull();
  expect(screen.getByLabelText('Your question').value).toBe('Can Cedar delete documents?');
});

test('passage indexing notice stays with the answer it applies to', async () => {
  vi.stubEnv('VITE_ENABLE_LIVE', 'true');
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
  const notice = 'Original passages are not available in search yet.';
  axios.post.mockResolvedValueOnce({ data: { summary: 'Saved summary answer.', results: [], retrieval_notice: notice } });
  const user = renderPage(AskQuestion, '/ask?mode=live');
  await user.type(screen.getByLabelText('Your question'), 'Cedar?{Enter}');
  expect(await screen.findByText(notice)).toHaveProperty('textContent', notice);
  axios.post.mockResolvedValueOnce({ data: { summary: 'Next answer.', results: [] } });
  await user.type(screen.getByLabelText('Your question'), 'Next question{Enter}');
  expect(await screen.findByText('Next answer.')).toBeTruthy();
  expect(screen.getByText(notice).closest('[role="article"]').getAttribute('aria-label')).toBe('Answer to: Cedar?');
  expect(screen.getByRole('article', { name: 'Answer to: Next question' }).textContent).not.toContain(notice);
});

test.each([
  [{ response: { status: 429, data: { detail: 'Daily allowance reached.' }, headers: { 'retry-after': '120' } } }, 'Daily allowance reached. Try again in about 2 minute(s).'],
  [{ code: 'ECONNABORTED' }, 'The request took too long. Your question or form is still here; try again or explore the demo.'],
  [{ message: 'Network Error' }, 'The live backend could not be reached. Check your connection, try again later, or explore the demo.'],
])('live errors are useful and retryable: %j', async (error, message) => {
  vi.stubEnv('VITE_ENABLE_LIVE', 'true');
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
  axios.post.mockRejectedValue(error);
  const user = renderPage(AskQuestion, '/ask?mode=live');
  await user.type(screen.getByLabelText('Your question'), 'Explain limits{Enter}');
  expect(await screen.findByText(message)).toBeTruthy();
  expect(screen.getByLabelText('Your question').value).toBe('Explain limits');
  expect(screen.queryByText('No internal resources matched this question.')).toBeNull();
});

test('switching to demo cancels the browser request and does not make another call', async () => {
  vi.stubEnv('VITE_ENABLE_LIVE', 'true');
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
  axios.post.mockReturnValue(new Promise(() => {}));
  const user = renderPage(AskQuestion, '/ask?mode=live');
  await user.type(screen.getByLabelText('Your question'), 'Explain limits{Enter}');
  const signal = axios.post.mock.calls[0][2].signal;
  await user.click(screen.getByRole('button', { name: 'Explore demo' }));
  expect(signal.aborted).toBe(true);
  expect(screen.getByText('Demo · saved examples')).toBeTruthy();
  expect(axios.post).toHaveBeenCalledTimes(1);
});

test('upload errors preserve the form and block duplicate submissions', async () => {
  vi.stubEnv('VITE_ENABLE_LIVE', 'true');
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
  let reject;
  axios.post.mockReturnValue(new Promise((resolve, fail) => { reject = fail; }));
  const user = renderPage(SubmitDocument, '/submit');
  await user.type(screen.getByLabelText('Title:'), 'Limits');
  await user.selectOptions(screen.getByLabelText('Media Type:'), 'article');
  await user.type(screen.getByLabelText('Article URL:'), 'https://example.com/limits');
  await user.type(screen.getByLabelText('Course Name:'), 'CALC101');
  await user.type(screen.getByLabelText('Description:'), 'A lesson');
  await user.dblClick(screen.getByRole('button', { name: 'Submit' }));
  expect(axios.post).toHaveBeenCalledTimes(1);
  expect(axios.post.mock.calls[0][2].timeout).toBe(90000);
  reject({ response: { status: 429, data: { detail: 'Daily allowance reached.' } } });
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByLabelText('Title:').value).toBe('Limits');
  expect(screen.getByRole('button', { name: 'Submit' }).disabled).toBe(false);
});
