import {beforeEach, expect, test, vi} from 'vitest';
import axios from 'axios';
import {AnswerStream, searchWithStream} from './searchStream';
vi.mock('axios',()=>({default:{post:vi.fn()}}));
beforeEach(()=>vi.clearAllMocks());
const event = data => `data: ${JSON.stringify(data)}\n\n`;
const sources = event({type:'sources',results:[{title:'Heap notes',passages:[{citation:'P1',text:'Evidence'}]}]});
const delta = event({type:'delta',text:'A heap'});
const done = event({type:'done'});

test('fragmented and repeated progress frames do not lose or duplicate text',()=>{
 const update=vi.fn(); const parser=new AnswerStream(update);
 const text=sources+delta+event({type:'delta',text:' is a tree.'})+done;
 for(let i=1;i<text.length;i+=7) parser.consume(text.slice(0,i));
 parser.consume(text);parser.consume(text);
 expect(parser.finish().summary).toBe('A heap is a tree.');
 expect(parser.finish().results[0].passages[0].text).toBe('Evidence');
 expect(update.mock.calls.some(([value])=>value.summary==='A heap')).toBe(true);
});

test.each([['missing completion',''],['provider error',event({type:'error',message:'Try later'})]])('%s discards incomplete answer but retains evidence',(_,ending)=>{
 const parser=new AnswerStream(()=>{});parser.consume(sources+delta+ending);
 expect(parser.finish()).toMatchObject({summary:null,answer_status:'unavailable',results:[{title:'Heap notes'}]});
});

test('transport delivers real partial updates before the request completes',async()=>{
 const update=vi.fn();
 axios.post.mockImplementation(async(_,__,options)=>{
  expect(options.headers.Accept).toBe('text/event-stream');
  options.onDownloadProgress({event:{target:{responseText:sources+delta}}});
  expect(update.mock.calls.at(-1)[0].summary).toBe('A heap');
  return {data:sources+delta+done};
 });
 const result=await searchWithStream('/api','question',new AbortController().signal,update);
 expect(result.summary).toBe('A heap');expect(axios.post).toHaveBeenCalledTimes(1);
});

test('network interruption retains already received sources without retrying',async()=>{
 axios.post.mockImplementation(async(_,__,options)=>{options.onDownloadProgress({event:{target:{responseText:sources+delta}}});throw {code:'ERR_NETWORK'};});
 const result=await searchWithStream('/api','question',new AbortController().signal,()=>{});
 expect(result.summary).toBeNull();expect(result.results[0].title).toBe('Heap notes');expect(axios.post).toHaveBeenCalledTimes(1);
});

test('pre-stream HTTP limit errors remain available to the UI',async()=>{
 axios.post.mockRejectedValue({response:{status:429,data:'{"detail":"Daily limit reached"}'}});
 await expect(searchWithStream('/api','question',new AbortController().signal,()=>{})).rejects.toMatchObject({response:{status:429,data:{detail:'Daily limit reached'}}});
});

test('cancellation does not publish late updates or fallback answers',async()=>{
 const abort=new AbortController();const update=vi.fn();
 axios.post.mockImplementation(async(_,__,options)=>{abort.abort();options.onDownloadProgress({event:{target:{responseText:sources}}});throw {code:'ERR_CANCELED'};});
 await expect(searchWithStream('/api','question',abort.signal,update)).rejects.toMatchObject({code:'ERR_CANCELED'});
 expect(update).not.toHaveBeenCalled();
});
