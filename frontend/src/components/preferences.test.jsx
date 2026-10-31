import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {PreferencesProvider,usePreferences} from './preferences';
let finish;
function Controls(){const prefs=usePreferences();finish ||= prefs.playCompletion;return <><button onClick={prefs.toggleSound}>Toggle</button><button onClick={()=>finish()}>Complete</button><span>{String(prefs.sound)}</span></>;}
beforeEach(()=>{localStorage.clear();finish=null;});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
test('sound does not initialize or play until opted in and disabling it stops later completions',()=>{
 const start=vi.fn(); const factory=vi.fn(function(){return {resume:()=>Promise.resolve(),close:()=>Promise.resolve(),currentTime:0,destination:{},createOscillator:()=>({frequency:{},connect:vi.fn(),start,stop:vi.fn()}),createGain:()=>({gain:{setValueAtTime:vi.fn(),linearRampToValueAtTime:vi.fn(),exponentialRampToValueAtTime:vi.fn()},connect:vi.fn()})};});
 vi.stubGlobal('AudioContext',factory);
 render(<PreferencesProvider><Controls/></PreferencesProvider>);
 fireEvent.click(screen.getByText('Complete'));expect(factory).not.toHaveBeenCalled();
 fireEvent.click(screen.getByText('Toggle'));fireEvent.click(screen.getByText('Complete'));
 expect(start).toHaveBeenCalledTimes(2);expect(localStorage.getItem('buddy:sound')).toBe('on');
 fireEvent.click(screen.getByText('Toggle'));fireEvent.click(screen.getByText('Complete'));
 expect(start).toHaveBeenCalledTimes(2);expect(localStorage.getItem('buddy:sound')).toBe('off');
});
