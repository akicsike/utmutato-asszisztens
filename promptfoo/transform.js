// A /api/chat SSE-streamet ad vissza ("data: {...}" sorok). A Promptfoo HTTP-providere a teljes választ
// szövegként kapja meg; ebből fűzzük össze a "delta" események szövegét a végső válasszá.
// A források száma és a hivatkozások metadataként is elérhetők (pl. állításokhoz, a riportban).
module.exports = (json, text) => {
  let output = '';
  let sources = 0;
  let cited = [];
  let error = null;
  for (const line of String(text || '').split('\n')) {
    if (!line.startsWith('data:')) continue;
    let ev;
    try {
      ev = JSON.parse(line.slice(5).trim());
    } catch (e) {
      continue;
    }
    if (ev.type === 'delta') output += ev.text;
    else if (ev.type === 'sources') sources = (ev.sources || []).length;
    else if (ev.type === 'done') cited = ev.cited || [];
    else if (ev.type === 'error') error = ev.message;
  }
  if (error) return { output: `[HIBA] ${error}`, metadata: { sources, cited } };
  return { output, metadata: { sources, cited } };
};
