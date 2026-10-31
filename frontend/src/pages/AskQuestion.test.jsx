import React from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen, within, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';
import AskQuestion from './AskQuestion';

vi.mock('axios', () => ({ default: { post: vi.fn() } }));

beforeEach(() => {
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
  vi.stubEnv('VITE_ENABLE_LIVE', 'true');
  vi.stubGlobal('SpeechRecognition', undefined);
  vi.stubGlobal('webkitSpeechRecognition', undefined);
  vi.stubGlobal('speechSynthesis', undefined);
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPage() {
  render(<React.StrictMode><MemoryRouter initialEntries={['/ask?mode=live']}><AskQuestion /></MemoryRouter></React.StrictMode>);
  return userEvent.setup();
}

test('typed questions work without speech APIs and display the answer', async () => {
  axios.post.mockResolvedValue({ data: { summary: 'A heap is a tree.', results: [] } });
  const user = renderPage();
  expect(screen.getByRole('button', { name: 'Start recording' }).disabled).toBe(true);
  await user.type(screen.getByLabelText('Your question'), 'What is a heap?{Enter}');
  expect(await screen.findByText('A heap is a tree.')).toBeTruthy();
  expect(axios.post).toHaveBeenCalledWith('https://api.example.test/search', { query: 'What is a heap?' }, expect.objectContaining({ timeout: 90000, signal: expect.any(AbortSignal), headers: {Accept:'text/event-stream'} }));
});

test('an in-flight question cannot be submitted twice', async () => {
  let resolve;
  axios.post.mockReturnValue(new Promise(done => { resolve = done; }));
  const user = renderPage();
  await user.type(screen.getByLabelText('Your question'), 'Explain trees');
  await user.dblClick(screen.getByRole('button', { name: 'Ask Buddy' }));
  expect(axios.post).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('Your question').disabled).toBe(true);
  resolve({ data: { summary: 'Tree answer', results: [] } });
  expect(await screen.findByText('Tree answer')).toBeTruthy();
});

test('service errors preserve the question for retry and do not claim no matches', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  axios.post.mockRejectedValue({ response: { data: { detail: 'AI processing timed out. Please try again.' } } });
  const user = renderPage();
  await user.type(screen.getByLabelText('Your question'), 'Explain sorting{Enter}');
  expect(await screen.findByText('AI processing timed out. Please try again.')).toBeTruthy();
  expect(screen.getByLabelText('Your question').value).toBe('Explain sorting');
  expect(screen.queryByText('No internal resources matched this question.')).toBeNull();
});

test('missing API configuration does not request an undefined address', async () => {
  vi.stubEnv('VITE_API_BASE_URL', '');
  vi.spyOn(console, 'error').mockImplementation(() => {});
  renderPage();
  expect(screen.getByText('Demo · saved examples')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Ask live' }).disabled).toBe(true);
  expect(axios.post).not.toHaveBeenCalled();
});

function sourcedAnswer(title, passage, summary = `${title} answer [P1]`) {
  return { data: { summary, results: [{
    // The same document may be retrieved with different excerpts in later turns.
    _id: 'shared-notes', title, summary: `${title} saved summary`, media_type: 'article',
    media_link: `https://example.com/${title.toLowerCase()}`,
    passages: [{ citation: 'P1', page: 1, text: passage }],
  }] } };
}

test.each(['https://youtu.be/abcdefghijk', 'https://youtube.com/shorts/abcdefghijk', 'invalid-youtube.com'])('video detail preview handles %s', async url => {
  const answer = sourcedAnswer('Video', 'Source text');
  answer.data.results[0].media_type = 'video';
  answer.data.results[0].media_link = url;
  axios.post.mockResolvedValueOnce(answer);
  const user = renderPage();
  await user.type(screen.getByLabelText('Your question'), 'Explain the video{Enter}');
  await user.click(await screen.findByText('Sources for this answer (1)'));
  await user.click(screen.getByRole('button', { name: 'View details for Video' }));
  if (url.startsWith('https:')) {
    expect(screen.getByTitle('YouTube Video').getAttribute('src')).toBe('https://www.youtube.com/embed/abcdefghijk');
  } else {
    expect(screen.queryByTitle('YouTube Video')).toBeNull();
    expect(screen.getByText('Preview unavailable for this video. Use Open Resource to view the original.')).toBeTruthy();
  }
  const dialog = screen.getByRole('dialog', { name: 'Video' });
  expect(dialog.open).toBe(true);
  fireEvent(dialog, new Event('cancel', { bubbles: false, cancelable: true }));
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'View details for Video' }));
});

test('consecutive answers retain their own P1 passages and resource details', async () => {
  axios.post.mockResolvedValueOnce(sourcedAnswer('Juniper', 'Maple is removed from the queue.'));
  let resolveSecond;
  axios.post.mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));
  const user = renderPage();
  await user.type(screen.getByLabelText('Your question'), 'Which item is removed?{Enter}');
  const first = await screen.findByRole('article', { name: 'Answer to: Which item is removed?' });
  await user.click(within(first).getByText('Sources for this answer (1)'));
  expect(within(first).getByText('[P1] Original document passage · Page 1')).toBeTruthy();
  expect(within(first).getByText('Maple is removed from the queue.')).toBeTruthy();

  await user.type(screen.getByLabelText('Your question'), 'What is the acceleration?{Enter}');
  expect(within(first).getByText('Maple is removed from the queue.')).toBeTruthy();
  resolveSecond(sourcedAnswer('Differentiation', 'Acceleration is six metres per second squared.'));
  const second = await screen.findByRole('article', { name: 'Answer to: What is the acceleration?' });
  await user.click(within(second).getByText('Sources for this answer (1)'));
  expect(within(second).getByText('[P1] Original document passage · Page 1')).toBeTruthy();
  expect(within(second).getByText('Acceleration is six metres per second squared.')).toBeTruthy();
  expect(within(first).queryByText('Acceleration is six metres per second squared.')).toBeNull();
  expect(within(second).queryByText('Maple is removed from the queue.')).toBeNull();
  expect(within(first).getByRole('link', { name: 'View Resource' }).getAttribute('href')).toBe('https://example.com/juniper');
  await user.click(within(first).getByRole('button', { name: 'View details for Juniper' }));
  expect(screen.getByRole('link', { name: 'Open Juniper in a new tab' }).getAttribute('href')).toBe('https://example.com/juniper');
  expect(screen.getByText('Juniper saved summary')).toBeTruthy();
});

test.each(['no matches', 'request failure'])('a later %s does not remove earlier sources', async (outcome) => {
  axios.post.mockResolvedValueOnce(sourcedAnswer('Juniper', 'Maple is removed.'));
  if (outcome === 'no matches') {
    axios.post.mockResolvedValueOnce({ data: { summary: 'General knowledge answer.', results: [] } });
  } else {
    axios.post.mockRejectedValueOnce({ response: { status: 503, data: { detail: 'Service unavailable.' } } });
  }
  const user = renderPage();
  await user.type(screen.getByLabelText('Your question'), 'Queue question{Enter}');
  const first = await screen.findByRole('article', { name: 'Answer to: Queue question' });
  await user.click(within(first).getByText('Sources for this answer (1)'));
  await user.type(screen.getByLabelText('Your question'), 'Another question{Enter}');
  const second = await screen.findByRole('article', { name: 'Answer to: Another question' });
  expect(within(first).getByText('Maple is removed.')).toBeTruthy();
  expect(within(second).queryByText('Maple is removed.')).toBeNull();
  expect(within(second).queryByText('Sources for this answer (1)')).toBeNull();
  if (outcome === 'no matches') {
    expect(within(second).getByText('No internal resources matched this question.')).toBeTruthy();
  } else {
    expect(within(second).getByText('Service unavailable.')).toBeTruthy();
    expect(within(second).queryByText('No internal resources matched this question.')).toBeNull();
  }
});

test('AI fallback evidence survives a successful retry of the same question', async () => {
  const fallback = sourcedAnswer('Juniper', 'The original retrieved passage.', null);
  fallback.data.answer_status = 'unavailable';
  fallback.data.error = { message: 'AI timed out.' };
  fallback.data.retrieval_notice = 'Some passages could not be searched.';
  axios.post.mockResolvedValueOnce(fallback).mockResolvedValueOnce(sourcedAnswer('Juniper', 'A newly retrieved passage.'));
  const user = renderPage();
  await user.type(screen.getByLabelText('Your question'), 'Queue question{Enter}');
  const first = await screen.findByRole('article', { name: 'Answer to: Queue question' });
  expect(within(first).getByText('Sources for this answer (1)').closest('details').open).toBe(true);
  await user.click(screen.getByRole('button', { name: 'Ask Buddy' }));
  await screen.findByText('Juniper answer [P1]');
  const [original, retry] = screen.getAllByRole('article', { name: 'Answer to: Queue question' });
  expect(within(original).getByText('The original retrieved passage.')).toBeTruthy();
  expect(within(original).getByRole('status').textContent).toBe('Some passages could not be searched.');
  await user.click(within(retry).getByText('Sources for this answer (1)'));
  expect(within(retry).getByText('A newly retrieved passage.')).toBeTruthy();
  expect(within(retry).queryByRole('status')).toBeNull();
});

test('streamed text appears before completion and an interrupted answer keeps its own source chips', async()=>{
 const encode=value=>`data: ${JSON.stringify(value)}\n\n`;
 let resolve;
 const resource=sourcedAnswer('Juniper','Original evidence.').data.results[0];
 const partial=encode({type:'sources',results:[resource]})+encode({type:'delta',text:'An unfinished explanation'});
 axios.post.mockImplementationOnce((_,__,options)=>{
  options.onDownloadProgress({event:{target:{responseText:partial}}});
  return new Promise(done=>{resolve=done;});
 });
 const user=renderPage();
 await user.type(screen.getByLabelText('Your question'),'Juniper limits?{Enter}');
 expect(await screen.findByText('An unfinished explanation')).toBeTruthy();
 expect(screen.getByRole('button',{name:'Asking...'}).disabled).toBe(true);
 resolve({data:partial+encode({type:'error',message:'The answer was interrupted.'})});
 expect(await screen.findByText('The answer was interrupted. Retrieved sources are available below.')).toBeTruthy();
 expect(screen.queryByText('An unfinished explanation')).toBeNull();
 const answer=screen.getByRole('article',{name:'Answer to: Juniper limits?'});
 await user.click(within(answer).getByRole('button',{name:/\[P1\].*Juniper/}));
 expect(screen.getByRole('dialog').textContent).toContain('Original evidence.');
 expect(axios.post).toHaveBeenCalledTimes(1);
});

test('voice input waits for browser start, preserves typed words and requires explicit submission', async()=>{
 let recognition;
 vi.stubGlobal('webkitSpeechRecognition',class {
  constructor(){recognition=this;}
  start=vi.fn();stop=vi.fn();abort=vi.fn();
 });
 const user=renderPage();
 await user.type(screen.getByLabelText('Your question'),'Explain');
 await user.click(screen.getByRole('button',{name:'Start recording'}));
 expect(screen.getByText(/Waiting for microphone access/)).toBeTruthy();
 await act(async()=>recognition.onstart());
 expect(screen.getByText(/Listening…/)).toBeTruthy();
 await act(async()=>recognition.onresult({results:[[{transcript:'heaps'}]]}));
 await user.click(screen.getByRole('button',{name:'Stop recording'}));
 await act(async()=>recognition.onend());
 expect(screen.getByLabelText('Your question').value).toBe('Explain heaps');
 expect(axios.post).not.toHaveBeenCalled();
 axios.post.mockResolvedValueOnce({data:{summary:'A heap is a tree.',results:[]}});
 await user.click(screen.getByRole('button',{name:'Ask Buddy'}));
 expect(await screen.findByText('A heap is a tree.')).toBeTruthy();
 expect(axios.post).toHaveBeenCalledTimes(1);
});
