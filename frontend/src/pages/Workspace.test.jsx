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
  localStorage.clear();
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

test('home demo action opens its lesson and shared navigation moves focus to the new page', async () => {
  const user = workspace();
  await user.click(screen.getByRole('link', { name: 'Explore demo' }));
  expect(screen.getByRole('region', { name: 'Sample lesson demo' })).toBeTruthy();
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

test('tour can be dismissed, stays dismissed and can be replayed', async()=>{
 const user=workspace();
 expect(screen.getByRole('dialog',{name:'Meet Buddy: quick tour'})).toBeTruthy();
 await user.click(screen.getByRole('button',{name:'Next'}));
 expect(screen.getByRole('heading',{name:'Ask live'})).toBeTruthy();
 await user.click(screen.getByRole('button',{name:'Close tour'}));
 expect(screen.queryByRole('dialog')).toBeNull();
 expect(localStorage.getItem('buddy:tour:v1')).toBe('seen');
 await user.click(screen.getByRole('link',{name:'Explore demo',exact:true}));
 await user.click(screen.getByRole('link',{name:'Buddy’s Brain home'}));
 expect(screen.queryByRole('dialog')).toBeNull();
 await user.click(screen.getByRole('link',{name:'Replay quick tour'}));
 expect(screen.getByRole('dialog',{name:'Meet Buddy: quick tour'})).toBeTruthy();
});

test('lesson progress survives navigation and resumes the same answer',async()=>{
 const user=workspace('/ask?lesson=heaps');
 const questions=screen.getAllByRole('button').filter(el=>el.closest('.suggested-questions'));
 await user.click(questions[0]);await user.click(questions[0]);
 expect(screen.getByRole('progressbar',{name:'Lesson progress'}).value).toBe(1);
 await user.click(questions[1]);
 expect(screen.getByRole('region',{name:'Lesson complete'})).toBeTruthy();
 await user.click(screen.getByRole('link',{name:'Buddy’s Brain home'}));
 await user.click(screen.getByRole('link',{name:/Continue where you left off/}));
 expect(screen.getByRole('progressbar',{name:'Lesson progress'}).value).toBe(2);
 expect(screen.getByRole('article').querySelector('h3').textContent).toBe(questions[1].textContent);
 expect(axios.post).not.toHaveBeenCalled();
});

test('dark preference persists and completion sound is opt-in',async()=>{
 const user=workspace();
 expect(screen.getByRole('button',{name:'Turn completion sounds on'}).getAttribute('aria-pressed')).toBe('false');
 await user.click(screen.getByRole('button',{name:'Use dark mode'}));
 expect(document.documentElement.dataset.theme).toBe('dark');
 expect(localStorage.getItem('buddy:dark')).toBe('on');
 await user.click(screen.getByRole('button',{name:'Use light mode'}));
 expect(document.documentElement.dataset.theme).toBe('light');
});

test('form preview follows the draft without submitting it',async()=>{
 const user=workspace('/submit');
 await user.type(screen.getByLabelText('Title:'),'Heap practice');
 expect(within(screen.getByRole('region',{name:'Resource preview'})).getByRole('heading',{name:'Heap practice'})).toBeTruthy();
 expect(axios.post).not.toHaveBeenCalled();
});
