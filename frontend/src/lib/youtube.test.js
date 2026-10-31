import { expect, test } from 'vitest';
import { youtubeEmbedUrl } from './youtube';

test.each([
  'https://www.youtube.com/watch?v=abcdefghijk&t=12',
  'https://youtu.be/abcdefghijk?si=share',
  'https://www.youtu.be/abcdefghijk',
  'https://youtube.com/shorts/abcdefghijk',
  'https://m.youtube.com/watch?v=abcdefghijk',
  'https://youtube.com/embed/abcdefghijk',
])('normalizes accepted video URL %s', url => {
  expect(youtubeEmbedUrl(url)).toBe('https://www.youtube.com/embed/abcdefghijk');
});

test.each(['not a URL', null, 'https://youtu.be/short', 'https://youtube.com.attacker.test/watch?v=abcdefghijk',
  'https://example.com/youtube.com/watch?v=abcdefghijk', 'javascript:alert(1)',
  'https://user:pass@youtube.com/watch?v=abcdefghijk', 'https://youtube.com:8080/watch?v=abcdefghijk'])('invalid or unsupported video URLs have no embed: %s', url => {
  expect(youtubeEmbedUrl(url)).toBeNull();
});
