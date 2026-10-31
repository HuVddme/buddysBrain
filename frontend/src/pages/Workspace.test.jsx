import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import AppShell from '../components/AppShell';
import Home from './Home';
import AskQuestion from './AskQuestion';
import SubmitDocument from './SubmitDocument';
import axios from 'axios';

vi.mock('axios', () => ({ default: { post: vi.fn() } }));
beforeEach(() => {
  vi.stubEnv('VITE_ENABLE_LIVE', 'true');
  vi.stubEnv('VITE_API_BASE_URL', '/api');
  vi.stubGlobal('scrollTo', vi.fn());
  vi.stubGlobal('SpeechRecognition', undefined);
  vi.stubGlobal('webkitSpeechRecognition', undefined);
  vi.stubGlobal('speechSynthesis', undefined);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks(); });

function HistoryControls() {
  const navigate = useNavigate(); const location = useLocation();
  return <><button onClick={() => navigate(-1)}>Browser back</button><button onClick={() => navigate(1)}>Browser forward</button><output aria-label="Current URL">{location.pathname}{location.search}</output></>;
}
function workspace(path = '/') {
  render(<MemoryRouter initialEntries={[path]}><HistoryControls/><Routes><Route element={<AppShell/>}>
    <Route path="/" element={<Home/>}/><Route path="/ask" element={<AskQuestion/>}/><Route path="/submit" element={<SubmitDocument/>}/>
  </Route></Routes></MemoryRouter>);
  return userEvent.setup();
}

test('demo/live mode, URL and active navigation stay synchronized through browser history', async () => {
  const user = workspace('/ask?lesson=heaps');
  expect(screen.getByRole('heading', { name: 'Binary heaps' })).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Ask live' }));
  expect(screen.getByLabelText('Current URL').textContent).toContain('mode=live');
  expect(within(screen.getByRole('navigation')).getByRole('link', { name: 'Ask live' }).getAttribute('aria-current')).toBe('page');
  await user.click(screen.getByRole('button', { name: 'Browser back' }));
  expect(screen.getByRole('heading', { name: 'Binary heaps' })).toBeTruthy();
  expect(screen.queryByLabelText('Your question')).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Browser forward' }));
  expect(screen.getByLabelText('Your question')).toBeTruthy();
  expect(axios.post).not.toHaveBeenCalled();
});

test('overview example opens its lesson and shared navigation moves focus to the new page', async () => {
  const user = workspace();
  await user.click(screen.getByRole('link', { name: 'Explore this saved example' }));
  expect(screen.getByRole('heading', { name: 'Binary heaps' })).toBeTruthy();
  expect(document.activeElement.id).toBe('main-content');
  await user.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'Add a resource' }));
  expect(screen.getByRole('heading', { name: 'Resource details' })).toBeTruthy();
  expect(document.title).toBe('Add a resource · Buddy’s Brain');
});

test('suggested live questions fill a draft without sending an AI request', async () => {
  const user = workspace('/ask?mode=live');
  await user.click(screen.getByRole('button', { name: 'What makes a function continuous?' }));
  expect(screen.getByLabelText('Your question').value).toBe('What makes a function continuous?');
  expect(document.activeElement).toBe(screen.getByLabelText('Your question'));
  expect(axios.post).not.toHaveBeenCalled();
});
