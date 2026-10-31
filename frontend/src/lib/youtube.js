// Match the URL forms accepted by the backend's YouTube transcript parser.
export function youtubeEmbedUrl(value) {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
        (url.port && !['80', '443'].includes(url.port))) return null;
    let id;
    if (['youtu.be', 'www.youtu.be'].includes(url.hostname)) {
      id = url.pathname.replace(/^\//, '');
    } else if (['youtube.com', 'www.youtube.com', 'm.youtube.com'].includes(url.hostname)) {
      if (url.pathname === '/watch') id = url.searchParams.get('v');
      else if (/^\/(shorts|embed)\//.test(url.pathname)) id = url.pathname.split('/')[2];
    }
    return /^[A-Za-z0-9_-]{11}$/.test(id || '') ? `https://www.youtube.com/embed/${id}` : null;
  } catch {
    return null;
  }
}
