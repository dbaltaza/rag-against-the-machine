/* RAG Workbench: a study guide for each pipeline stage plus lab tools.
   Every demo calls the project's own code through the local API. */
(() => {
  'use strict';

  // ------------------------------------------------------------------ utils
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));

  function h(tag, props, ...kids) {
    const e = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') e.className = v;
        else if (k === 'text') e.textContent = v;
        else if (k === 'html') e.innerHTML = v;
        else if (k === 'style') e.style.cssText = v;
        else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const c of kids.flat(Infinity)) {
      if (c === null || c === undefined || c === false) continue;
      e.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return e;
  }

  const store = {
    get(k, d) { try { const v = localStorage.getItem('rag.' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('rag.' + k, JSON.stringify(v)); } catch { /* storage unavailable */ } }
  };

  async function api(path, body) {
    const opts = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    let res;
    try { res = await fetch(path, opts); } catch { throw new Error('The workbench server is not answering. Start it again with "make serve".'); }
    let data = null;
    try { data = await res.json(); } catch { /* not JSON */ }
    if (!res.ok) {
      const d = data && data.detail;
      const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join('; ') : '';
      throw new Error(msg || `The request failed with status ${res.status}.`);
    }
    return data;
  }

  const n0 = (v) => Number(v).toLocaleString('en-US');
  const f2 = (v) => Number(v).toFixed(2);
  const f3 = (v) => Number(v).toFixed(3);
  const secs = (ms) => (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
  const kindOf = (p) => (/\.pyi?$/.test(p) ? 'py' : /\.(md|markdown)$/.test(p) ? 'md' : 'txt');
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
  function pathEl(p) {
    const i = p.lastIndexOf('/');
    return h('span', { class: 'path' }, h('span', { class: 'dir' }, p.slice(0, i + 1)), p.slice(i + 1));
  }
  function ticker(el, prefix) {
    const t0 = performance.now();
    const tick = () => { el.textContent = `${prefix}${((performance.now() - t0) / 1000).toFixed(1)} s`; };
    tick();
    const id = setInterval(tick, 100);
    return () => { clearInterval(id); return performance.now() - t0; };
  }
  function busy(btn, label) {
    const old = btn.textContent;
    btn.textContent = label; btn.disabled = true;
    return () => { btn.textContent = old; btn.disabled = false; };
  }

  // ------------------------------------------------------------------ icons
  const ICONS = {
    flow: '<circle cx="5" cy="12" r="2.2"/><circle cx="19" cy="12" r="2.2"/><circle cx="12" cy="12" r="2.2"/><path d="M7.2 12h2.6M14.2 12h2.6"/>',
    files: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/>',
    chunk: '<rect x="4" y="4" width="16" height="6.5" rx="1.6"/><rect x="4" y="13.5" width="16" height="6.5" rx="1.6"/>',
    token: '<path d="M8 5H5v14h3M16 5h3v14h-3"/><path d="M10 12h4"/>',
    rank: '<path d="M6 20v-8M12 20V5M18 20v-5"/>',
    prompt: '<rect x="5" y="3" width="14" height="18" rx="2.2"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    gen: '<path d="M12 3v5M12 16v5M3 12h5M16 12h5M6.3 6.3l2.8 2.8M14.9 14.9l2.8 2.8M6.3 17.7l2.8-2.8M14.9 9.1l2.8-2.8"/>',
    eval: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.2"/>',
    search: '<circle cx="11" cy="11" r="6.2"/><path d="M20 20l-4.6-4.6"/>',
    chart: '<path d="M4 20h16"/><path d="M6.5 16l4-5 3 3 4.5-6.5"/>',
    index: '<path d="M12 3l8.5 4.6L12 12.2 3.5 7.6z"/><path d="M3.5 12.2L12 16.8l8.5-4.6"/><path d="M3.5 16.4L12 21l8.5-4.6"/>'
  };
  const svg = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  const icon = (name, color) => h('i', { class: 'ico', style: `--c:${color}`, html: svg(name) });
  $$('.side-nav [data-icon]').forEach((i) => { i.innerHTML = svg(i.dataset.icon); });

  // ------------------------------------------------------------------ health
  let health = null;
  const healthWaiters = [];
  async function loadHealth() {
    try {
      health = await api('/health');
      $('#led').className = 'led ok';
      $('#status-text').textContent = `Index loaded: ${n0(health.chunks)} chunks from ${n0(health.files)} files`;
    } catch (e) {
      health = null;
      $('#led').className = 'led bad';
      $('#status-text').textContent = e.message;
    }
    healthWaiters.splice(0).forEach((fn) => fn(health));
    return health;
  }
  const whenHealth = () => new Promise((resolve) => (health ? resolve(health) : healthWaiters.push(resolve)));

  // ------------------------------------------------------------------ sheet
  const fileCache = new Map();
  let sheetSource = null;
  async function openSource(src) {
    sheetSource = src;
    const sheet = $('#sheet');
    sheet.hidden = false;
    $('#sheet-path').replaceChildren(pathEl(src.file_path));
    $('#sheet-meta').textContent = `Characters ${n0(src.first_character_index)} to ${n0(src.last_character_index)}`;
    const body = $('#sheet-body');
    body.textContent = 'Opening the file…';
    try {
      if (!fileCache.has(src.file_path)) fileCache.set(src.file_path, (await api('/file?path=' + encodeURIComponent(src.file_path))).text);
    } catch (e) { body.textContent = e.message; return; }
    if (sheetSource !== src) return;
    const text = fileCache.get(src.file_path);
    const a = Math.max(0, src.first_character_index), b = Math.min(text.length, src.last_character_index);
    const mark = h('mark', null, text.slice(a, b));
    body.replaceChildren(text.slice(0, a), mark, text.slice(b));
    const l1 = text.slice(0, a).split('\n').length;
    const l2 = l1 + text.slice(a, b).split('\n').length - 1;
    $('#sheet-meta').textContent = `Characters ${n0(a)} to ${n0(b)} · lines ${l1} to ${l2} · ${n0(b - a)} characters`;
    requestAnimationFrame(() => mark.scrollIntoView({ block: 'center' }));
  }
  function closeSheet() { $('#sheet').hidden = true; sheetSource = null; }
  $('#sheet-close').addEventListener('click', closeSheet);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#sheet').hidden) closeSheet(); });
  $('#sheet-copy').addEventListener('click', async () => {
    if (!sheetSource) return;
    const json = JSON.stringify({ file_path: sheetSource.file_path, first_character_index: sheetSource.first_character_index, last_character_index: sheetSource.last_character_index }, null, 2);
    const btn = $('#sheet-copy');
    try { await navigator.clipboard.writeText(json); btn.textContent = 'Copied'; } catch { btn.textContent = 'Copy failed'; }
    setTimeout(() => { btn.textContent = 'Copy source'; }, 1400);
  });

  // ------------------------------------------------------------------ building blocks
  function pageHead(iconName, color, kicker, title, lead) {
    return h('header', null,
      h('div', { class: 'kicker' }, icon(iconName, color), kicker),
      h('h1', null, title),
      lead ? h('p', { class: 'lead' }, lead) : null);
  }
  const prose = (html) => h('div', { class: 'prose', html });
  const section = (title, ...kids) => h('section', { class: 'section' }, title ? h('h2', null, title) : null, ...kids);
  function qa(items) {
    return section('Questions an evaluator might ask',
      h('p', { class: 'muted small', style: 'margin:0' }, 'Answer out loud first, then open the card to check yourself.'),
      h('div', { class: 'list' }, items.map(([q, a]) => h('details', { class: 'qa' }, h('summary', null, q), h('div', { class: 'answer', html: a })))));
  }
  const ORDER = ['overview', 'chunking', 'tokenizing', 'ranking', 'prompt', 'generating', 'recall'];
  const TITLES = { overview: 'How it works', chunking: 'Chunking', tokenizing: 'Tokenizing', ranking: 'Ranking with BM25', prompt: 'Building the prompt', generating: 'Generating the answer', recall: 'Measuring recall', workbench: 'Workbench', index: 'Index' };
  function nextNav(name) {
    const i = ORDER.indexOf(name);
    const prev = i > 0 ? ORDER[i - 1] : null;
    const next = i < ORDER.length - 1 ? ORDER[i + 1] : 'workbench';
    return h('nav', { class: 'next', 'aria-label': 'Chapters' },
      prev ? h('a', { href: `#/${prev}` }, h('span', null, 'Previous'), h('b', null, TITLES[prev])) : null,
      h('a', { href: `#/${next}`, class: 'fwd' }, h('span', null, next === 'workbench' ? 'Now try it yourself' : 'Next'), h('b', null, TITLES[next])));
  }
  function seg(options, value, onChange, label) {
    const box = h('div', { class: 'seg', role: 'group', 'aria-label': label || 'Options' });
    let current = value;
    const buttons = options.map(([v, text]) => h('button', {
      type: 'button', 'aria-pressed': String(v === value),
      onclick: () => { if (buttons.find((b) => b.dataset.v === String(v)).disabled) return; current = v; buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === String(v)))); onChange(v); }
    }, text));
    buttons.forEach((b, i) => { b.dataset.v = String(options[i][0]); });
    box.append(...buttons);
    box.value = () => current;
    box.disable = (v, off) => { const b = buttons.find((x) => x.dataset.v === String(v)); if (b) { b.disabled = off; b.title = off ? 'Build the index with embeddings first (Lab › Index)' : ''; } };
    return box;
  }
  function slider(label, min, max, step, value, color, onInput) {
    const out = h('output', null, n0(value));
    const input = h('input', { type: 'range', min, max, step, value, 'aria-label': label });
    input.addEventListener('input', () => { out.textContent = n0(input.value); onInput(Number(input.value)); });
    return Object.assign(h('label', { class: 'slider', style: `--c:${color}` }, h('span', { class: 'field-label' }, label), out, input), { input, out });
  }
  function searchBox(placeholder, value, big) {
    const input = h('input', { class: 'search' + (big ? ' big' : ''), type: 'search', placeholder, value: value || '', 'aria-label': placeholder });
    const wrap = h('div', { class: 'search-wrap' + (big ? ' big' : ''), html: svg('search') });
    wrap.append(input);
    return { wrap, input };
  }
  const stat = (k, v, cls) => h('div', { class: 'stat' }, h('div', { class: 'v' + (cls ? ' ' + cls : '') }, v), h('div', { class: 'k' }, k));
  const errorLine = () => h('p', { class: 'error', role: 'alert' });
  function hitRow(hit, i, extra) {
    return h('div', { class: 'hit', tabindex: '0', onclick: () => openSource(hit), onkeydown: (e) => { if (e.key === 'Enter') openSource(hit); } },
      h('div', { class: 'hit-top' }, h('span', { class: 'rank' }, i + 1), pathEl(hit.file_path), h('span', { class: 'tag ' + kindOf(hit.file_path) }, kindOf(hit.file_path))),
      h('div', { class: 'hit-meta' }, `Characters ${n0(hit.first_character_index)} to ${n0(hit.last_character_index)} · ${n0(hit.last_character_index - hit.first_character_index)} wide${hit.score !== undefined ? ` · score ${f2(hit.score)}` : ''}`),
      extra || (hit.text ? h('div', { class: 'snip' }, hit.text) : null));
  }
  function copyRow(cmd, note) {
    const btn = h('button', { class: 'btn plain', type: 'button' }, 'Copy');
    btn.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(cmd); btn.textContent = 'Copied'; } catch { btn.textContent = 'Select it'; }
      setTimeout(() => { btn.textContent = 'Copy'; }, 1400);
    });
    return h('div', null, h('div', { class: 'cmd' }, h('code', null, cmd), btn), note ? h('p', { class: 'muted small', style: 'margin:-4px 16px 10px' }, note) : null);
  }

  // ================================================================== GUIDE

  // ---------------------------------------------------------------- overview
  function pageOverview() {
    const nums = {};
    const stages = [
      ['files', 'var(--c-corpus)', 'files', 'Files in data/raw', '#/index'],
      ['chunks', 'var(--c-chunk)', 'chunk', 'Chunks, at most 2,000 characters', '#/chunking'],
      ['terms', 'var(--c-token)', 'token', 'Distinct terms in the vocabulary', '#/tokenizing'],
      ['k', 'var(--c-rank)', 'rank', 'Best chunks kept by BM25', '#/ranking'],
      ['budget', 'var(--c-prompt)', 'prompt', 'Token budget for sources', '#/prompt'],
      ['model', 'var(--c-gen)', 'gen', 'Model writes the answer', '#/generating'],
      ['recall', 'var(--c-eval)', 'eval', 'Recall@5 target, docs and code', '#/recall']
    ];
    const pulse = h('i', { class: 'pulse', 'aria-hidden': 'true' });
    const track = h('div', { class: 'track' }, pulse, stages.map(([key, color, ic, label, href]) => {
      nums[key] = h('div', { class: 'n' }, '—');
      return h('a', { class: 'stage', href }, icon(ic, color), nums[key], h('div', { class: 't' }, label));
    }));
    nums.k.textContent = 'Top 5';
    nums.budget.textContent = '3,000';
    nums.model.textContent = 'Qwen3';
    nums.recall.textContent = '0.80 / 0.50';
    whenHealth().then((hd) => {
      nums.files.textContent = n0(hd.files);
      nums.chunks.textContent = n0(hd.chunks);
      nums.terms.textContent = n0(hd.vocabulary);
    });
    requestAnimationFrame(() => pulse.classList.add('go'));

    const stageList = h('div', { class: 'list' },
      [
        ['chunk', 'var(--c-chunk)', 'Index', 'Read every useful file, cut it into chunks, count the terms in each chunk and save the counts under data/processed/. This runs once, in about 5 seconds.', '#/chunking'],
        ['rank', 'var(--c-rank)', 'Retrieve', 'Turn the question into terms and score every chunk with BM25. The top k chunks become sources: a file path and two character offsets.', '#/ranking'],
        ['prompt', 'var(--c-prompt)', 'Augment', 'Put the best sources, in order, into the model’s prompt until a 3,000-token budget is full, with instructions to answer only from them.', '#/prompt'],
        ['gen', 'var(--c-gen)', 'Generate', 'Qwen3-0.6B reads the prompt and writes a short answer grounded in those sources.', '#/generating'],
        ['eval', 'var(--c-eval)', 'Evaluate', 'Compare your sources with the reference sources. A reference counts as found when one of yours is in the same file and overlaps it enough.', '#/recall']
      ].map(([ic, c, t, d, href]) => h('a', { class: 'list-row click', href, style: 'text-decoration:none;color:inherit;align-items:flex-start' },
        icon(ic, c), h('div', { class: 'grow' }, h('h3', null, t), h('div', { class: 'muted small' }, d)), h('span', { class: 'chev' }, '›'))));

    const commands = h('div', { class: 'list' },
      copyRow('uv run python -m src index --max_chunk_size 2000', 'Walks data/raw, chunks and tokenizes every file, writes chunks.jsonl, term_frequencies.npz, vocabulary.json and manifest.json.'),
      copyRow('uv run python -m src search "How do I load a LoRA adapter?" --k 5', 'Loads the index and prints the top 5 sources with their character spans.'),
      copyRow('uv run python -m src search_dataset --dataset_path data/datasets/UnansweredQuestions/dataset_docs_public.json --k 10 --save_directory data/output/search_results/UnansweredQuestions', 'Searches every question and writes a StudentSearchResults JSON file.'),
      copyRow('uv run python -m src evaluate --student_search_results_path data/output/search_results/UnansweredQuestions/dataset_docs_public.json --dataset_path data/datasets/AnsweredQuestions/dataset_docs_public.json', 'Your own recall@k check. The official score comes from the moulinette.'),
      copyRow('uv run python -m src answer_dataset --student_search_results_path data/output/search_results/UnansweredQuestions/dataset_docs_public.json --save_directory data/output/search_results_and_answer/UnansweredQuestions', 'Re-reads each source from disk and asks Qwen3 for an answer to every question.'));

    const files = [
      ['src/__main__.py', 'Entry point. Runs the Fire CLI and turns any error into one clean line.'],
      ['src/cli.py', 'Every command, with argument checks for k, paths and chunk size.'],
      ['src/pipeline.py', 'Connects the stages and loads each part only when it is needed.'],
      ['src/models.py', 'The pydantic models from the subject, plus Chunk and ScoredSource.'],
      ['src/chunking/', 'Python chunking with ast, Markdown chunking on headings.'],
      ['src/tokenizer.py', 'Turns text into terms, splitting identifiers.'],
      ['src/index/indexer.py', 'Walks the corpus, builds or updates the index.'],
      ['src/index/bm25.py', 'Sparse term counts and BM25 weights.'],
      ['src/retrieval/retriever.py', 'Lexical, semantic and hybrid search.'],
      ['src/generation/generator.py', 'Prompt building and Qwen3 decoding.'],
      ['src/evaluation.py', 'IoU and recall@k, the same rules as the moulinette.'],
      ['src/api.py', 'This workbench’s server and the bonus HTTP API.']
    ];
    const fileGrid = h('div', { class: 'list' }, files.map(([f, d]) => h('div', { class: 'list-row', style: 'align-items:flex-start' }, h('span', { class: 'file-ref', style: 'min-width:0;flex:none' }, f), h('span', { class: 'muted small' }, d))));

    const rules = h('div', { class: 'stats' },
      stat('Widest source allowed', '2,000 chars'),
      stat('Recall@5 on docs', '≥ 0.80'),
      stat('Recall@5 on code', '≥ 0.50'),
      stat('Indexing time', '≤ 5 min'),
      stat('200 questions searched', '≤ 90 s'),
      stat('Model', 'Qwen3-0.6B'));

    return h('div', { class: 'page' },
      pageHead('flow', 'var(--c-corpus)', 'Guide', 'How your RAG system answers a question', 'A question comes in. The system finds the few places in vLLM’s code and docs that talk about it, then a small local model writes an answer from only those places. Each chapter takes one step, explains what your code does there, and lets you run it on the real index.'),
      track,
      section('The stages', prose('<p>The subject names four stages: indexing, retrieving, augmenting and generating. Evaluation sits beside them and is what the moulinette grades.</p>'), stageList),
      section('The limits you are graded on', rules, prose('<p>Every <code>file_path</code> must be written exactly as in the corpus, starting with <code>data/raw/vllm-0.10.1/</code>. The grader compares paths character by character. The CLI must also survive odd input (an empty query, <code>k=0</code>, a missing file, broken JSON) without a traceback.</p>')),
      section('What each command does', commands),
      section('Where the code lives', fileGrid),
      qa([
        ['Explain RAG in one sentence.', '<p>Instead of retraining a model to know a codebase, you search the codebase at question time and give the model the few relevant snippets to answer from.</p>'],
        ['Why not give the model the whole repository?', '<p>It doesn’t fit: vLLM is thousands of files, and Qwen3-0.6B only gets your 3,000-token source budget. Even a model with a huge context answers worse when the evidence is buried in noise. Retrieval picks the 2 or 3 snippets that matter.</p>'],
        ['Why a lexical method instead of embeddings?', '<p>The subject requires TF-IDF or BM25, and code questions often quote identifiers verbatim, which exact term matching handles well. Your README measured it: BM25 alone reaches 0.88 on docs and 0.85 on code, MiniLM embeddings alone 0.66 and 0.58, and the hybrid 0.85 and 0.79.</p>'],
        ['What is saved in data/processed/?', '<p><code>chunks.jsonl</code> (every chunk’s path, offsets and text), <code>term_frequencies.npz</code> (a sparse chunks × terms count matrix), <code>vocabulary.json</code> (term → column) and <code>manifest.json</code> (sizes, counts and a hash of every file, used for incremental indexing).</p>'],
        ['Which command does the evaluator run first?', '<p>The reference script runs <code>uv sync</code>, then <code>index</code>, <code>search_dataset</code> into a folder scoped by dataset, and the moulinette’s <code>evaluate_student_search_results</code> on that file. The path layout in the README must match for it to work.</p>']
      ]),
      nextNav('overview'));
  }

  // ---------------------------------------------------------------- chunking
  const PRESET_FILES = [
    'data/raw/vllm-0.10.1/vllm/lora/request.py',
    'data/raw/vllm-0.10.1/vllm/sampling_params.py',
    'data/raw/vllm-0.10.1/docs/features/lora.md',
    'data/raw/vllm-0.10.1/docs/getting_started/quickstart.md'
  ];
  function pageChunking() {
    const st = { path: store.get('chunk.path', PRESET_FILES[0]), max: store.get('chunk.max', 2000), min: store.get('chunk.min', 800), sel: -1 };
    const err = errorLine();
    const { wrap, input } = searchBox('Find a file, e.g. scheduler.py or quantization', '');
    const suggest = h('div', { class: 'suggest', hidden: true });
    wrap.append(suggest);
    const current = h('div', { class: 'small muted' });
    const stats = h('div', { class: 'stats' });
    const minimap = h('div', { class: 'minimap', role: 'img', 'aria-label': 'Chunk sizes along the file' });
    const filetext = h('div', { class: 'filetext' });
    const out = h('div', { style: 'display:flex;flex-direction:column;gap:12px' }, stats, minimap, filetext);

    const findFiles = debounce(async () => {
      const q = input.value.trim();
      if (!q) { suggest.hidden = true; return; }
      try {
        const list = await api('/learn/files?q=' + encodeURIComponent(q));
        suggest.replaceChildren(...(list.length ? list.map((p) => h('button', { type: 'button', onclick: () => { suggest.hidden = true; input.value = ''; choose(p); } }, p.replace('data/raw/vllm-0.10.1/', ''))) : [h('div', { class: 'hint', style: 'padding:10px 12px' }, 'No indexed file matches.')]));
        suggest.hidden = false;
      } catch (e) { err.textContent = e.message; }
    }, 180);
    input.addEventListener('input', findFiles);
    input.addEventListener('keydown', (e) => { if (e.key === 'Escape') suggest.hidden = true; });
    document.addEventListener('click', (e) => { if (!wrap.contains(e.target)) suggest.hidden = true; });

    const maxS = slider('Max chunk size (--max_chunk_size)', 100, 2000, 50, st.max, 'var(--c-chunk)', (v) => { st.max = v; store.set('chunk.max', v); run(); });
    const minS = slider('Merge small neighbours up to', 0, 2000, 50, st.min, 'var(--c-chunk)', (v) => { st.min = v; store.set('chunk.min', v); run(); });

    function choose(p) { st.path = p; store.set('chunk.path', p); run(); }
    const run = debounce(async () => {
      err.textContent = '';
      current.replaceChildren('Showing ', h('span', { class: 'file-ref' }, st.path.replace('data/raw/vllm-0.10.1/', '')));
      try {
        const d = await api('/learn/chunk', { path: st.path, max_chunk_size: st.max, min_chunk_size: Math.min(st.min, st.max) });
        render(d);
      } catch (e) { err.textContent = e.message; }
    }, 150);

    function render(d) {
      const sizes = d.chunks.map((c) => c.size);
      const avg = sizes.length ? sizes.reduce((a, b) => a + b, 0) / sizes.length : 0;
      stats.replaceChildren(
        stat('Strategy', d.strategy === 'python' ? 'Python (ast)' : 'Markdown'),
        stat('File length', n0(d.length) + ' chars'),
        stat('Chunks', n0(d.chunks.length)),
        stat('Average size', n0(Math.round(avg))),
        stat('Largest', n0(Math.max(0, ...sizes)), Math.max(0, ...sizes) > 2000 ? 'bad' : ''));
      minimap.replaceChildren(...d.chunks.map((c, i) => h('span', { style: `flex:${Math.max(c.size, 1)} 1 0`, title: `Chunk ${i + 1}: ${n0(c.size)} characters`, onclick: () => select(i) })));
      const nodes = [];
      let pos = 0;
      d.chunks.forEach((c, i) => {
        if (c.first_character_index > pos) nodes.push(h('span', { class: 'cband', style: 'border-left-color:transparent;background:transparent' }, h('span', { class: 'clabel', style: 'color:var(--ink-3)' }, 'Not in any chunk (blank)'), d.text.slice(pos, c.first_character_index)));
        nodes.push(h('span', { class: 'cband', 'data-i': i, onclick: () => select(i) }, h('span', { class: 'clabel' }, `Chunk ${i + 1} · ${n0(c.size)} characters · [${c.first_character_index}:${c.last_character_index}]`), d.text.slice(c.first_character_index, c.last_character_index)));
        pos = c.last_character_index;
      });
      if (pos < d.text.length) nodes.push(h('span', { class: 'cband', style: 'border-left-color:transparent;background:transparent' }, h('span', { class: 'clabel', style: 'color:var(--ink-3)' }, 'Not in any chunk (blank)'), d.text.slice(pos)));
      filetext.replaceChildren(...nodes);
      filetext.scrollTop = 0;
    }
    function select(i) {
      $$('.minimap span', out).forEach((s, j) => s.classList.toggle('sel', j === i));
      $$('.cband[data-i]', out).forEach((b) => b.classList.toggle('sel', Number(b.dataset.i) === i));
      const band = $(`.cband[data-i="${i}"]`, out);
      if (band) filetext.scrollTo({ top: band.offsetTop - filetext.offsetTop - 8, behavior: 'smooth' });
    }

    const panel = h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('div', { class: 'panel-title', style: '--c:var(--c-chunk)' }, h('i', { class: 'dot' }), 'Chunk a real file'), current),
      h('div', { class: 'row' }, wrap),
      h('div', { class: 'chips' }, PRESET_FILES.map((p) => h('button', { class: 'chip', type: 'button', onclick: () => choose(p) }, p.split('/').slice(-1)[0]))),
      h('div', { class: 'row', style: 'gap:24px' }, maxS, minS),
      h('p', { class: 'hint', style: 'margin:0' }, 'Your index uses 2,000 and 800. Drag them and watch the boundaries move. Click a bar or a chunk to select it.'),
      err, out);
    run();

    return h('div', { class: 'page' },
      pageHead('chunk', 'var(--c-chunk)', 'Step 1 of the index', 'Chunking', 'Retrieval can’t return a whole file: the moulinette rejects any source wider than 2,000 characters, and a whole file would drown the model. So each file is cut into chunks, and a chunk is what search returns.'),
      prose(`<p>The indexer picks a strategy from the extension (<span class="file-ref">strategy_for</span> in <span class="file-ref">src/chunking/base.py</span>). <code>.py</code> and <code>.pyi</code> go to the Python chunker. <code>.md</code>, <code>.txt</code>, <code>.rst</code> and <code>.markdown</code> go to the Markdown chunker. Everything else is skipped, and so are the <code>tests/</code>, <code>benchmarks/</code>, <code>.github/</code> and <code>.buildkite/</code> folders.</p>
        <p><b>Python</b> (<span class="file-ref">src/chunking/python.py</span>) parses the file with <code>ast</code>. Every top-level statement is a candidate chunk, and each boundary sits at the end of the previous statement, so the comments and decorators above a <code>def</code> stay with it. A class over the limit is cut on its methods. Anything still too big is cut on line boundaries, and a single line over the limit is cut by characters. A file that doesn’t parse falls back to line splitting.</p>
        <p><b>Markdown</b> (<span class="file-ref">src/chunking/markdown.py</span>) cuts on headings <code>#</code> to <code>######</code> that sit outside fenced code blocks, so one chunk is one section. An oversized section is cut on blank lines, keeping each fenced block whole.</p>
        <p>Last, <span class="file-ref">pack_spans</span> merges small neighbours until they reach the merge size, never going over the maximum. Chunks tile the file: each one is exactly <code>text[start:end]</code>, and those two numbers are the <code>first_character_index</code> and <code>last_character_index</code> the grader reads.</p>`),
      panel,
      qa([
        ['What happens to a function longer than 2,000 characters?', '<p>It is cut on line boundaries by <code>split_by_lines</code>, and a single line longer than the limit is cut at character level. No chunk can ever be wider than <code>--max_chunk_size</code>, which is what keeps the output valid.</p>'],
        ['Why merge small chunks up to 800 characters?', '<p>An import block or a one-line constant on its own is noise for BM25, and many tiny chunks scatter a function’s vocabulary. Your measurements: no merging gave 0.86 on docs and 0.78 on code, merging up to 800 gave 0.88 and 0.85, and 1,200 dropped code to 0.84 because larger chunks overlap short reference spans less (see Measuring recall).</p>'],
        ['Why character offsets and not lines or bytes?', '<p>The reference spans are Python string indices on the UTF-8 decoded text, so every chunk is built as a slice <code>text[start:end]</code>. The tests check that slicing the file with a chunk’s offsets gives back exactly the chunk’s text.</p>'],
        ['Why two strategies?', '<p>The subject asks for them, and the units of meaning differ: code is organised in statements, functions and classes, docs in sections under headings. Cutting a doc page with <code>ast</code> is impossible, and cutting code on blank lines would split functions in the middle.</p>'],
        ['What if someone passes --max_chunk_size 5000?', '<p>The CLI rejects it with an error message, no traceback. One source over 2,000 characters would make the whole results file invalid for the moulinette.</p>']
      ]),
      nextNav('chunking'));
  }

  // ---------------------------------------------------------------- tokenizing
  function pageTokenizing() {
    const presets = ['How do I load a LoRA adapter at runtime?', 'What does FusedMoEActivationFormat control?', 'What is the default value of max_num_seqs?', 'vllm/entrypoints/openai/api_server.py'];
    const ta = h('textarea', { class: 'input', rows: '2', 'aria-label': 'Text to tokenize', style: 'resize:vertical;min-height:56px' });
    ta.value = store.get('tok.text', presets[1]);
    const err = errorLine();
    const words = h('div', { class: 'words' });
    const bag = h('div', { class: 'toks' });
    const count = h('span', { class: 'hint' });
    const run = debounce(async () => {
      store.set('tok.text', ta.value);
      err.textContent = '';
      try {
        const d = await api('/learn/tokenize', { text: ta.value.slice(0, 5000) });
        words.replaceChildren(...(d.length ? d.map((w) => {
          const stop = w.tokens.length === 0;
          return h('div', { class: 'word' + (stop ? ' stop' : '') }, h('span', { class: 'src' }, w.word),
            h('div', { class: 'toks' }, stop ? h('span', { class: 'tok none' }, 'stop word') : w.tokens.map((t, i) => h('span', { class: 'tok' + (i === 0 && w.tokens.length > 1 ? ' whole' : '') }, t))));
        }) : [h('span', { class: 'hint' }, 'Type something to see its tokens.')]));
        const all = d.flatMap((w) => w.tokens);
        const counts = new Map();
        all.forEach((t) => counts.set(t, (counts.get(t) || 0) + 1));
        bag.replaceChildren(...[...counts].map(([t, c]) => h('span', { class: 'tok' }, c > 1 ? `${t} ×${c}` : t)));
        count.textContent = `${all.length} tokens, ${counts.size} distinct`;
      } catch (e) { err.textContent = e.message; }
    }, 160);
    ta.addEventListener('input', run);
    run();

    const panel = h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('div', { class: 'panel-title', style: '--c:var(--c-token)' }, h('i', { class: 'dot' }), 'Tokenize any text'), count),
      ta,
      h('div', { class: 'chips' }, presets.map((p) => h('button', { class: 'chip', type: 'button', onclick: () => { ta.value = p; run(); } }, p.length > 42 ? p.slice(0, 40) + '…' : p))),
      err,
      h('div', { class: 'field-label' }, 'Word by word. A dark chip is the identifier kept whole, light chips are its parts.'),
      words,
      h('div', { class: 'field-label' }, 'What BM25 sees: the bag of terms'),
      bag);

    return h('div', { class: 'page' },
      pageHead('token', 'var(--c-token)', 'Step 2 of the index', 'Tokenizing', 'BM25 matches terms, not meaning, so one tokenizer turns every chunk and every question into a bag of terms. Its job is to let a question match the code whether it paraphrases an idea or quotes an identifier.'),
      prose(`<p><span class="file-ref">tokenize</span> in <span class="file-ref">src/tokenizer.py</span> applies these rules in order:</p>
        <ol>
          <li>Find words with the pattern <code>[A-Za-z0-9_]+</code>.</li>
          <li>If a word is an identifier with several parts, keep it whole in lowercase and also add each part. <code>snake_case</code> splits on underscores and <code>camelCase</code> on capitals, so <code>FusedMoEActivationFormat</code> gives <code>fusedmoeactivationformat</code>, <code>fused</code>, <code>mo</code>, <code>e</code>, <code>activation</code> and <code>format</code>.</li>
          <li>Drop a trailing plural <code>s</code> from words longer than four letters that don’t end in <code>ss</code>: <code>adapters</code> becomes <code>adapter</code>, <code>seqs</code> stays.</li>
          <li>Remove about 120 stop words such as <i>the</i>, <i>how</i> and <i>is</i>.</li>
        </ol>
        <p>A chunk is not indexed as its text alone. <span class="file-ref">index_text_for</span> in <span class="file-ref">src/index/indexer.py</span> puts the file’s path in front of it twice, so a question that names a module or a page, like <i>lora</i> or <i>triton_flash_attention</i>, matches every chunk of that file. Removing the path cost 4 points of recall on docs and 13 on code.</p>`),
      panel,
      qa([
        ['Why keep an identifier whole and also split it?', '<p>A question may quote <code>max_num_seqs</code> exactly, and the whole token matches it precisely. Another may say “maximum number of sequences”, and the parts <code>max</code> and <code>num</code> catch that. Keeping both covers the two kinds of question the subject warns about.</p>'],
        ['Why must queries and chunks use the same tokenizer?', '<p>A query term only scores if it is exactly a column of the vocabulary. Any difference in lowercasing, splitting or plural handling would make question terms miss chunk terms that mean the same thing.</p>'],
        ['Why does “LoRA” become lora, lo and ra?', '<p>The camelCase pattern sees <code>Lo</code> then <code>RA</code>. The whole token <code>lora</code> is still kept, so exact matches still work, and the two parts add a little noise. An evaluator may spot this in the tokenizer demo, so it is worth knowing.</p>'],
        ['Why strip plurals only from words over four letters?', '<p>Short words often end in s without being plurals (<code>args</code>, <code>bus</code>, <code>gas</code>). The rule only touches longer words and skips double s (<code>class</code>, <code>process</code>).</p>'],
        ['Why not use a stemming library?', '<p>A stemmer would mangle identifiers, which matter most for code questions. The hand-written rules are small, fast and predictable, and the measured recall is well above the thresholds.</p>']
      ]),
      nextNav('tokenizing'));
  }

  // ---------------------------------------------------------------- ranking
  const TERM_COLORS = ['var(--c-rank)', 'var(--accent)', 'var(--c-eval)', 'var(--c-prompt)', 'var(--c-gen)', 'var(--c-chunk)', 'var(--c-token)', '#ffcc00', '#a2845e', 'var(--ink-3)'];
  function pageRanking() {
    const { wrap, input } = searchBox('Ask something, e.g. How do I enable prefix caching?', store.get('bm.q', 'How do I load a LoRA adapter at runtime?'));
    let k = store.get('bm.k', 5);
    const kSeg = seg([[3, '3'], [5, '5'], [10, '10']], k, (v) => { k = v; store.set('bm.k', v); run(); }, 'Number of results');
    const err = errorLine();
    const out = h('div', { style: 'display:flex;flex-direction:column;gap:18px' });
    async function run() {
      const q = input.value.trim();
      store.set('bm.q', input.value);
      err.textContent = '';
      if (!q) { out.replaceChildren(h('p', { class: 'hint' }, 'Type a question to see how BM25 scores it.')); return; }
      try { render(await api('/learn/bm25', { query: q, k })); } catch (e) { err.textContent = e.message; }
    }
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });

    function render(d) {
      const colorOf = new Map(d.terms.map((t, i) => [t.term, TERM_COLORS[i % TERM_COLORS.length]]));
      const maxIdf = Math.log((d.documents + 0.5) / 0.5 + 1);
      const termTable = h('div', { class: 'tablewrap' }, h('table', { class: 'terms' },
        h('thead', null, h('tr', null, h('th', null, 'Term'), h('th', null, 'In question'), h('th', null, 'Chunks with it (df)'), h('th', null, 'Rarity (idf)'), h('th', { style: 'width:30%' }, ''))),
        h('tbody', null, d.terms.length ? d.terms.map((t) => h('tr', null,
          h('td', null, h('i', { class: 'swatch', style: `background:${colorOf.get(t.term)}` }), h('code', null, t.term)),
          h('td', null, `×${t.count}`),
          h('td', null, t.in_vocabulary ? n0(t.document_frequency) : h('span', { class: 'tag bad' }, 'not in index')),
          h('td', null, t.in_vocabulary ? f3(t.idf) : '—'),
          h('td', null, t.in_vocabulary ? h('div', { class: 'bar', style: `--c:${colorOf.get(t.term)}` }, h('i', { style: `width:${(t.idf / maxIdf) * 100}%` })) : null)))
          : h('tr', null, h('td', { colspan: '5', class: 'hint' }, 'Every word was a stop word, so nothing can match.')))));

      const maxScore = Math.max(...d.hits.map((x) => x.score), 1e-9);
      const hits = h('div', { class: 'list' }, d.hits.length ? d.hits.map((hit, i) => {
        const detail = h('div', { hidden: true, style: 'padding:0 16px 16px;display:flex;flex-direction:column;gap:12px' });
        const stack = h('div', { class: 'stack', style: `width:${(hit.score / maxScore) * 100}%` }, hit.terms.map((t) => h('i', { style: `flex:${t.contribution} 1 0;background:${colorOf.get(t.term)}`, title: `${t.term}: ${f3(t.contribution)}` })));
        const row = h('div', { class: 'hit', tabindex: '0' },
          h('div', { class: 'hit-top' }, h('span', { class: 'rank' }, i + 1), pathEl(hit.file_path), h('b', { style: 'font-variant-numeric:tabular-nums' }, f2(hit.score))),
          h('div', { style: 'padding-left:28px' }, stack),
          h('div', { class: 'hit-meta' }, `${n0(hit.length)} terms in this chunk (average ${n0(Math.round(d.average_length))}) · click to see the maths`));
        const toggle = () => {
          detail.hidden = !detail.hidden;
          if (!detail.hidden && !detail.childElementCount) buildDetail(detail, hit, d, colorOf);
        };
        row.addEventListener('click', toggle);
        row.addEventListener('keydown', (e) => { if (e.key === 'Enter') toggle(); });
        return h('div', null, row, detail);
      }) : h('div', { class: 'list-row hint' }, 'No chunk scored above zero, so search returns nothing. That is on purpose: random chunks would be worse than none.'));

      out.replaceChildren(
        h('div', { class: 'stats' }, stat('Chunks (N)', n0(d.documents)), stat('Average length (avgdl)', n0(Math.round(d.average_length)) + ' terms'), stat('k1', String(d.k1)), stat('b', String(d.b))),
        h('div', { class: 'field-label' }, 'The question’s terms, rarest score highest'),
        termTable,
        h('div', { class: 'field-label' }, 'Top chunks, each bar split by how much each term added'),
        hits);
    }

    function buildDetail(box, hit, d, colorOf) {
      const calc = h('div', { class: 'calc' });
      const showCalc = (t, tr) => {
        $$('tr', box).forEach((x) => x.classList.toggle('sel', x === tr));
        const term = d.terms.find((x) => x.term === t.term);
        const N = d.documents, df = term.document_frequency, k1 = d.k1, b = d.b;
        const idf = Math.log((N - df + 0.5) / (df + 0.5) + 1);
        const norm = 1 - b + b * hit.length / d.average_length;
        const w = idf * t.tf * (k1 + 1) / (t.tf + k1 * norm);
        calc.innerHTML = '';
        calc.append(
          h('div', null, 'term   = ', h('b', null, t.term)),
          h('div', null, `idf    = ln((N − df + 0.5) / (df + 0.5) + 1) = ln((${n0(N)} − ${n0(df)} + 0.5) / (${n0(df)} + 0.5) + 1) = `, h('b', null, f3(idf))),
          h('div', null, `norm   = 1 − b + b · |d| / avgdl = 1 − ${b} + ${b} · ${n0(hit.length)} / ${f2(d.average_length)} = `, h('b', null, f3(norm))),
          h('div', null, `weight = idf · tf · (k1 + 1) / (tf + k1 · norm) = ${f3(idf)} · ${t.tf} · ${k1 + 1} / (${t.tf} + ${k1} · ${f3(norm)}) = `, h('b', null, f3(w))),
          h('div', null, `added  = weight × ${term.count} (times in the question) = `, h('b', null, f3(w * term.count)), `   index says ${f3(t.contribution)}`));
      };
      const rows = hit.terms.map((t) => {
        const tr = h('tr', { class: 'click', tabindex: '0' },
          h('td', null, h('i', { class: 'swatch', style: `background:${colorOf.get(t.term)}` }), h('code', null, t.term)),
          h('td', null, String(t.tf)), h('td', null, f3(t.weight)), h('td', null, f3(t.contribution)));
        tr.addEventListener('click', (e) => { e.stopPropagation(); showCalc(t, tr); });
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') showCalc(t, tr); });
        return [tr, t];
      });
      box.append(
        h('div', { class: 'tablewrap' }, h('table', { class: 'terms' }, h('thead', null, h('tr', null, h('th', null, 'Term'), h('th', null, 'Times in chunk (tf)'), h('th', null, 'Weight'), h('th', null, 'Added to score'))), h('tbody', null, rows.map((r) => r[0])))),
        calc,
        h('div', { class: 'row' }, h('button', { class: 'btn gray', type: 'button', onclick: () => openSource(hit) }, 'Open in file'), h('span', { class: 'hint' }, 'The indexed text starts with the path twice, which is why path words count.')));
      if (rows.length) showCalc(rows[0][1], rows[0][0]);
    }

    const panel = h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('div', { class: 'panel-title', style: '--c:var(--c-rank)' }, h('i', { class: 'dot' }), 'Score a question'), kSeg),
      h('div', { class: 'row' }, wrap, h('button', { class: 'btn', type: 'button', onclick: run }, 'Rank')),
      err, out);
    run();

    return h('div', { class: 'page' },
      pageHead('rank', 'var(--c-rank)', 'Retrieve', 'Ranking with BM25', 'BM25 scores every chunk against the question’s terms and keeps the top k. It rewards rare terms, rewards repeats with diminishing returns, and stops long chunks from winning only because they are long.'),
      h('div', { class: 'formula' }, `idf(t)   = ln( (N − df + 0.5) / (df + 0.5) + 1 )\nw(d, t)  = idf(t) · tf · (k1 + 1) / ( tf + k1 · (1 − b + b · |d| / avgdl) )\nscore(d) = Σ  w(d, t) × (times t appears in the question)`),
      prose(`<p><b>N</b> is the number of chunks, <b>df</b> how many chunks contain the term, <b>tf</b> how often it appears in this chunk, <b>|d|</b> the chunk’s length in terms and <b>avgdl</b> the average length. Your index uses <b>k1 = 1.5</b> and <b>b = 0.75</b>.</p>
        <p><span class="file-ref">src/index/bm25.py</span> saves only raw counts: a sparse chunks × terms matrix (scipy CSR) in <code>term_frequencies.npz</code>. The weights are computed once when the index loads, so answering a query only adds up a few matrix columns, then <code>np.argpartition</code> finds the top k. A chunk that scores zero is never returned, so a nonsense query gives an empty list.</p>`),
      panel,
      qa([
        ['Why BM25 rather than TF-IDF?', '<p>Your chunks range from a few dozen to 2,000 characters, so length normalisation matters. BM25 also saturates term frequency, so a chunk that repeats one identifier 40 times can’t beat a chunk that matches several different query terms.</p>'],
        ['What do k1 and b do?', '<p><b>k1</b> controls how fast extra repeats stop helping: with 1.5 the tenth occurrence adds much less than the first. <b>b</b> controls length normalisation: 0 ignores length, 1 fully divides by relative length. 0.75 is the standard compromise.</p>'],
        ['Why the + 1 inside the log?', '<p>The classic idf goes negative for terms found in more than half of the chunks, which would punish a chunk for containing them. Adding 1 keeps every idf positive, the same choice Lucene makes.</p>'],
        ['Why multiply by how often the term appears in the question?', '<p>A term the question repeats is probably central to it. The query is turned into term counts and each column is added that many times.</p>'],
        ['How fast is retrieval, and why?', '<p>About 0.1 seconds for 199 questions, far under the 90-second limit. The weights are precomputed once and a query touches only the columns of its own terms in a sparse matrix.</p>']
      ]),
      nextNav('ranking'));
  }

  // ---------------------------------------------------------------- prompt
  function pagePrompt() {
    const { wrap, input } = searchBox('A question to build a prompt for', store.get('pr.q', 'How do I load a LoRA adapter at runtime?'));
    let k = store.get('pr.k', 5);
    const kSeg = seg([[3, '3'], [5, '5'], [10, '10']], k, (v) => { k = v; store.set('pr.k', v); }, 'Sources');
    const btn = h('button', { class: 'btn', type: 'button' }, 'Build the prompt');
    const time = h('span', { class: 'hint' });
    const err = errorLine();
    const out = h('div', { style: 'display:flex;flex-direction:column;gap:14px' });
    async function run() {
      const q = input.value.trim();
      store.set('pr.q', input.value);
      err.textContent = '';
      if (!q) { err.textContent = 'Type a question first.'; return; }
      const done = busy(btn, 'Building…');
      const stop = ticker(time, 'Loading the Qwen3 tokenizer, first time only… ');
      try {
        const d = await api('/learn/prompt', { query: q, k });
        time.textContent = `Built in ${secs(stop())}`;
        render(d);
      } catch (e) { stop(); time.textContent = ''; err.textContent = e.message; }
      finally { done(); }
    }
    btn.addEventListener('click', run);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });

    function render(d) {
      const used = d.sources.filter((s) => s.included).reduce((a, s) => a + s.tokens, 0);
      const included = d.sources.filter((s) => s.included).length;
      const parts = d.prompt.split(/(<\|im_start\|>\w+|<\|im_end\|>)/g).map((p, i) => (i % 2 ? h('span', { class: 'role' }, p) : p));
      out.replaceChildren(
        h('div', { class: 'stats' }, stat('Sources in the prompt', `${included} of ${d.sources.length}`), stat('Tokens used by sources', `${n0(used)} / ${n0(d.budget)}`), stat('Whole prompt', n0(d.prompt_tokens) + ' tokens')),
        h('div', { class: 'budget', role: 'img', 'aria-label': `${used} of ${d.budget} tokens used` }, d.sources.filter((s) => s.included).map((s, i) => h('i', { style: `width:${Math.min(100, (s.tokens / d.budget) * 100)}%`, title: `Source ${i + 1}: ${s.tokens} tokens` }))),
        h('div', { class: 'list' }, d.sources.map((s, i) => h('div', { class: 'list-row click', onclick: () => openSource(s) },
          h('span', { class: 'rank' }, i + 1), pathEl(s.file_path), h('span', { class: 'hint', style: 'white-space:nowrap' }, `${n0(s.tokens)} tokens`), h('span', { class: 'tag ' + (s.included ? 'ok' : 'bad') }, s.included ? 'included' : 'left out')))),
        h('div', { class: 'field-label' }, 'The exact text Qwen3 receives'),
        h('pre', { class: 'code' }, parts));
    }

    const panel = h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('div', { class: 'panel-title', style: '--c:var(--c-prompt)' }, h('i', { class: 'dot' }), 'Build a real prompt'), kSeg),
      h('div', { class: 'row' }, wrap, btn), time, err, out);

    return h('div', { class: 'page' },
      pageHead('prompt', 'var(--c-prompt)', 'Augment', 'Building the prompt', 'Retrieval hands over ranked chunks. Augmenting means putting the right amount of them in front of the model, in a format it understands, with instructions that keep it on those sources.'),
      prose(`<p><span class="file-ref">build_context</span> in <span class="file-ref">src/generation/generator.py</span> walks the sources in rank order. Each becomes a block headed <code>[Source n] path (chars a-b)</code> followed by its text. It counts each block’s tokens with Qwen’s own tokenizer and stops before the total passes <b>3,000 tokens</b>. If the first source alone is too big, it is truncated so there is always some context.</p>
        <p>The system message is short and strict: answer only from the snippets, quote identifiers, values and commands exactly, say so when the context doesn’t contain the answer, and don’t repeat the question. The user message is the context, then the question. The chat template is applied with <code>enable_thinking=False</code> so Qwen3 doesn’t spend its tokens reasoning out loud.</p>`),
      panel,
      qa([
        ['Why a token budget and not a character budget?', '<p>The model’s limits are counted in tokens, and code turns into many more tokens per character than prose. Counting with the model’s own tokenizer is the only exact measure.</p>'],
        ['Why keep sources in rank order?', '<p>The best evidence goes first, where a small model pays most attention, and when the budget runs out it is the weakest sources that get dropped.</p>'],
        ['Why turn thinking off?', '<p>Qwen3 normally writes a <code>&lt;think&gt;</code> block first. At 0.6B it tends to ramble and repeat the question, using up the 256 new tokens. With thinking off the answers are short and mostly grounded. Any leftover <code>&lt;think&gt;</code> block is still stripped as a safety net.</p>'],
        ['How do you limit hallucination?', '<p>The system prompt allows only the context and asks the model to say when the answer is missing. With no sources the model isn’t called at all and a fixed message is returned. Decoding is greedy, so the model takes its most likely token at each step instead of sampling.</p>']
      ]),
      nextNav('prompt'));
  }

  // ---------------------------------------------------------------- generating
  function pageGenerating() {
    const { wrap, input } = searchBox('Ask Qwen3 about vLLM', store.get('gen.q', 'How do I enable prefix caching?'));
    const btn = h('button', { class: 'btn', type: 'button' }, 'Generate');
    const err = errorLine();
    const out = h('div', { style: 'display:flex;flex-direction:column;gap:14px' });
    async function run() {
      const q = input.value.trim();
      store.set('gen.q', input.value);
      err.textContent = '';
      if (!q) { err.textContent = 'Type a question first.'; return; }
      const done = busy(btn, 'Generating…');
      try {
        const hits = await api('/explore', { query: q, k: 5 });
        const text = h('p', null, h('span', { class: 'typing' }, h('i'), h('i'), h('i')));
        const meta = h('span');
        out.replaceChildren(
          h('div', { class: 'answer-card' }, h('div', { class: 'who' }, icon('gen', 'var(--c-gen)'), 'Qwen3-0.6B ', meta), text),
          h('div', { class: 'field-label' }, 'Sources it was given'),
          h('div', { class: 'list' }, hits.map((hit, i) => hitRow(hit, i, h('span')))));
        const stop = ticker(meta, '· ');
        try {
          const res = await api('/answer', { query: q, k: 5 });
          text.textContent = res.answer;
          meta.textContent = `· ${secs(stop())}`;
        } catch (e) { stop(); text.textContent = ''; err.textContent = e.message; }
      } catch (e) { err.textContent = e.message; }
      finally { done(); }
    }
    btn.addEventListener('click', run);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });

    const panel = h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('div', { class: 'panel-title', style: '--c:var(--c-gen)' }, h('i', { class: 'dot' }), 'Generate an answer'), h('span', { class: 'hint' }, 'The first answer also loads the model, about 15 s')),
      h('div', { class: 'row' }, wrap, btn), err, out);

    return h('div', { class: 'page' },
      pageHead('gen', 'var(--c-gen)', 'Generate', 'Generating the answer', 'Qwen3-0.6B reads the prompt and writes the answer. At 0.6 billion parameters it runs on a laptop, and for the same reason it needs clean context and tight instructions.'),
      prose(`<p><span class="file-ref">Generator.answer</span> loads the model only on first use, so <code>index</code>, <code>search</code> and <code>evaluate</code> never pay for it. It picks CUDA, then Apple’s MPS, then the CPU, in half precision on a GPU.</p>
        <p>Decoding is greedy (<code>do_sample=False</code>) with a mild <code>repetition_penalty</code> of 1.1 and at most 256 new tokens. Any <code>&lt;think&gt;</code> block is removed from the output. An empty question or an empty source list gets a fixed reply without calling the model.</p>
        <p><code>answer_dataset</code> reads a search results file that holds only offsets. It re-reads each span from disk with <code>text[first:last]</code>, so it works on results from any retriever.</p>`),
      panel,
      qa([
        ['Why is the model loaded lazily?', '<p>Loading Qwen3 and torch takes seconds and gigabytes. Retrieval commands and the moulinette flow never need it, so they stay fast.</p>'],
        ['Why greedy decoding?', '<p>It is deterministic: the same question and sources always give the same answer, which makes results reproducible during the defense, and it keeps a small model from wandering.</p>'],
        ['How does answer_dataset get the text when the results only have offsets?', '<p>It opens each <code>file_path</code> (cached per file) and slices the characters between the two indices. The spans are the contract, not the text.</p>'],
        ['Can the project use another model?', '<p>Yes, with <code>--model_name</code>. The subject allows it as long as everything still works with the default, Qwen/Qwen3-0.6B.</p>'],
        ['What makes a satisfactory answer?', '<p>Coherent, grounded in the retrieved sources with no major invention, and on point. The subject says grading favours retrieval quality, grounding and prompt strategy over perfect wording, because of the model’s size.</p>']
      ]),
      nextNav('generating'));
  }

  // ---------------------------------------------------------------- recall
  function pageRecall() {
    const L = 3000;
    const st = store.get('iou', { r0: 1000, r1: 1060, g0: 0, g1: 2000 });
    const track = h('div', { class: 'iou-track', role: 'img', 'aria-label': 'Reference and retrieved spans' });
    const refEl = h('i', { class: 'iou-span ref' }), gotEl = h('i', { class: 'iou-span got' }), interEl = h('i', { class: 'iou-span inter' });
    track.append(refEl, gotEl, interEl);
    const res = h('div', { class: 'stats' });
    const verdict = h('div', { class: 'verdict' });
    const sl = {};
    const mk = (key, label, color) => { sl[key] = slider(label, 0, L, 10, st[key], color, (v) => { st[key] = v; draw(); }); return sl[key]; };
    function draw() {
      store.set('iou', st);
      const r0 = Math.min(st.r0, st.r1), r1 = Math.max(st.r0, st.r1), g0 = Math.min(st.g0, st.g1), g1 = Math.max(st.g0, st.g1);
      const inter = Math.max(0, Math.min(r1, g1) - Math.max(r0, g0));
      const union = (r1 - r0) + (g1 - g0) - inter;
      const iou = union > 0 ? inter / union : 0;
      const pct = (v) => `${(v / L) * 100}%`;
      Object.assign(refEl.style, { left: pct(r0), width: `max(3px, ${pct(r1 - r0)})` });
      Object.assign(gotEl.style, { left: pct(g0), width: `max(3px, ${pct(g1 - g0)})` });
      interEl.hidden = inter === 0;
      Object.assign(interEl.style, { left: pct(Math.max(r0, g0)), width: pct(inter) });
      res.replaceChildren(stat('Reference width', n0(r1 - r0)), stat('Your source width', n0(g1 - g0)), stat('Overlap', n0(inter)), stat('Union', n0(union)), stat('IoU', f3(iou), iou >= 0.05 ? 'ok' : 'bad'));
      const wide = g1 - g0 > 2000;
      verdict.className = 'verdict ' + (iou >= 0.05 && !wide ? 'ok' : 'bad');
      verdict.textContent = wide ? 'Invalid: a source wider than 2,000 characters makes the whole file fail validation.'
        : iou >= 0.05 ? 'Counts as found: same file and IoU of at least 0.05.' : inter > 0 ? 'Not found: they overlap, but the IoU is under 0.05.' : 'Not found: no overlap.';
    }
    const presets = [
      ['Tiny reference, 2,000-char chunk', { r0: 1000, r1: 1060, g0: 0, g1: 2000 }],
      ['Same reference, 800-char chunk', { r0: 1000, r1: 1060, g0: 600, g1: 1400 }],
      ['Shifted chunk', { r0: 800, r1: 1600, g0: 1400, g1: 2400 }],
      ['Exact match', { r0: 900, r1: 1500, g0: 900, g1: 1500 }],
      ['Too wide', { r0: 900, r1: 1500, g0: 0, g1: 2600 }]
    ];
    const iouPanel = h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('div', { class: 'panel-title', style: '--c:var(--c-eval)' }, h('i', { class: 'dot' }), 'Does this source count?'), h('span', { class: 'hint' }, 'One file, characters 0 to 3,000')),
      h('div', { class: 'chips' }, presets.map(([t, v]) => h('button', { class: 'chip', type: 'button', onclick: () => { Object.assign(st, v); Object.keys(sl).forEach((key) => { sl[key].input.value = st[key]; sl[key].out.textContent = n0(st[key]); }); draw(); } }, t))),
      track,
      h('div', { class: 'legend' }, h('span', null, h('i', { class: 'swatch', style: 'background:var(--c-eval)' }), 'Reference source'), h('span', null, h('i', { class: 'swatch', style: 'background:var(--accent)' }), 'Your source'), h('span', null, 'Dashed box: overlap')),
      h('div', { class: 'grid2' }, h('div', { style: 'display:flex;flex-direction:column;gap:10px' }, mk('r0', 'Reference start', 'var(--c-eval)'), mk('r1', 'Reference end', 'var(--c-eval)')), h('div', { style: 'display:flex;flex-direction:column;gap:10px' }, mk('g0', 'Your source start', 'var(--accent)'), mk('g1', 'Your source end', 'var(--accent)'))),
      res, verdict);
    draw();

    const scoreBtn = h('button', { class: 'btn', type: 'button' }, 'Score both public datasets');
    const scoreErr = errorLine();
    const scoreOut = h('div');
    scoreBtn.addEventListener('click', async () => {
      scoreErr.textContent = '';
      const done = busy(scoreBtn, 'Scoring…');
      try {
        const names = await api('/datasets');
        const pick = (re) => names.find((x) => re.test(x));
        const runs = [['Docs', pick(/doc/i), 0.8], ['Code', pick(/code/i), 0.5]].filter((r) => r[1]);
        const results = await Promise.all(runs.map(([, name]) => api('/evaluate', { dataset: name, k: 10, mode: 'lexical' })));
        scoreOut.replaceChildren(h('div', { class: 'tablewrap' }, h('table', { class: 'terms' },
          h('thead', null, h('tr', null, h('th', null, 'Dataset'), h('th', null, 'Questions'), ...['1', '3', '5', '10'].map((k) => h('th', null, `Recall@${k}`)), h('th', null, 'Target @5'))),
          h('tbody', null, results.map((r, i) => h('tr', null, h('td', null, runs[i][0]), h('td', null, String(r.questions.length)),
            ...['1', '3', '5', '10'].map((k) => h('td', { style: k === '5' ? 'font-weight:650' : '' }, h('span', { class: k === '5' ? (r.recall[k] >= runs[i][2] ? 'pill ok' : 'pill bad') : '' }, f3(r.recall[k])))),
            h('td', null, f2(runs[i][2]))))))));
      } catch (e) { scoreErr.textContent = e.message; }
      finally { done(); }
    });
    const scorePanel = h('div', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('div', { class: 'panel-title', style: '--c:var(--c-eval)' }, h('i', { class: 'dot' }), 'Your scores right now'), scoreBtn),
      h('p', { class: 'hint', style: 'margin:0' }, 'Runs every public question through your retriever with k = 10 and applies the rules above. Takes well under a second.'),
      scoreErr, scoreOut);

    return h('div', { class: 'page' },
      pageHead('eval', 'var(--c-eval)', 'Evaluate', 'Measuring recall', 'The moulinette never reads your answers. It checks whether your top k sources point at the same places as the reference sources, and turns that into recall@k.'),
      h('div', { class: 'formula' }, `recall@k (one question) = references found in your top k / number of references\nfound                   = same file_path  and  IoU ≥ 0.05\nIoU                     = overlap / (|reference| + |yours| − overlap)\nscore                   = average over all questions`),
      prose(`<p>Before scoring, the results file is validated: no source may be wider than 2,000 characters (<code>--max_context_length</code>) and no question may have more than k sources. <span class="file-ref">src/evaluation.py</span> re-implements these rules for your <code>evaluate</code> command. The official number comes from the moulinette, which your code never imports or calls.</p>
        <p>The overlap bar is low, but not zero. Try the first preset: a correct 2,000-character chunk around a 60-character reference has an IoU of only 0.03, so it doesn’t count. That is one reason your chunks are merged only up to 800 characters.</p>`),
      iouPanel,
      scorePanel,
      qa([
        ['Why can a chunk that contains the answer still not count?', '<p>If the chunk is much wider than the reference, the IoU falls under 0.05. A 60-character reference inside a 2,000-character chunk gives 0.03. Smaller chunks keep the IoU up but split a function’s vocabulary across chunks, which hurts BM25. 800 characters was the best trade-off you measured.</p>'],
        ['Why must file_path match exactly?', '<p>The grader compares paths as strings. <code>vllm/lora/request.py</code> or an absolute path would never match <code>data/raw/vllm-0.10.1/vllm/lora/request.py</code>, so every result in that file would count as missed.</p>'],
        ['What is the difference between your evaluate and the moulinette?', '<p>Same rules (same file, IoU ≥ 0.05, mean over questions, width and count checks), but yours is for iterating quickly. The defense uses the moulinette binary, which you ran through Docker on your Mac and which gave 0.880 on docs and 0.848 on code at k = 5.</p>'],
        ['Why report several k values?', '<p>Recall@1 shows whether the best source comes first, which matters for the prompt. Recall@5 is what you are graded on. Recall@10 shows how much is found but ranked too low, which points at ranking problems rather than chunking ones.</p>']
      ]),
      nextNav('recall'));
  }

  // ================================================================== LAB

  // ---------------------------------------------------------------- workbench
  // One screen: query bar, results / history / dataset on the left, the
  // source file in the middle, and an inspector (why it ranked, answer,
  // prompt, chunk) on the right. State survives leaving the page.
  const WB = {
    q: store.get('wb.q', ''), k: store.get('wb.k', 5), mode: store.get('wb.mode', 'lexical'),
    hits: [], bm: null, sel: -1, refs: null, refQuestion: null,
    left: 'results', tab: store.get('wb.tab', 'why'),
    answers: new Map(), prompts: new Map(), searchMs: null,
    ds: store.get('wb.ds', null), dsData: null, dsFilter: 'all',
    boundaries: store.get('wb.bounds', false), history: store.get('wb.history', [])
  };
  const keyOf = (q, k, mode) => `${mode}|${k}|${q}`;
  const sameSpan = (a, b) => a.file_path === b.file_path && a.first_character_index === b.first_character_index && a.last_character_index === b.last_character_index;
  function iou(a, b) {
    if (a.file_path !== b.file_path) return 0;
    const inter = Math.max(0, Math.min(a.last_character_index, b.last_character_index) - Math.max(a.first_character_index, b.first_character_index));
    if (!inter) return 0;
    const union = (a.last_character_index - a.first_character_index) + (b.last_character_index - b.first_character_index) - inter;
    return union > 0 ? inter / union : 0;
  }
  const refMatch = (hit) => (WB.refs ? WB.refs.some((r) => iou(r, hit) >= 0.05) : false);

  function pageWorkbench() {
    // ---- toolbar
    const sideBtn = h('button', { class: 'tool-btn', type: 'button', title: 'Show or hide the sidebar', 'aria-label': 'Toggle sidebar' }, h('span', { html: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M9.5 5v14"/></svg>' }));
    sideBtn.addEventListener('click', () => { const off = !store.get('wb.sideoff', false); store.set('wb.sideoff', off); $('.app').classList.toggle('side-off', off); });
    const { wrap, input } = searchBox('Ask about the vLLM codebase', WB.q);
    const kbdHint = h('span', { class: 'kbd-in' }, '⌘K');
    wrap.append(kbdHint);
    const kSel = h('select', { class: 'select', 'aria-label': 'Number of sources' }, [3, 5, 10, 20].map((v) => new Option(`Top ${v}`, String(v))));
    kSel.value = String(WB.k);
    kSel.addEventListener('change', () => { WB.k = Number(kSel.value); store.set('wb.k', WB.k); });
    const mSeg = seg([['lexical', 'BM25'], ['semantic', 'Semantic'], ['hybrid', 'Hybrid']], WB.mode, (v) => { WB.mode = v; store.set('wb.mode', v); }, 'Retrieval mode');
    whenHealth().then((hd) => {
      const off = !hd.semantic;
      mSeg.disable('semantic', off); mSeg.disable('hybrid', off);
      if (off && WB.mode !== 'lexical') { WB.mode = 'lexical'; $$('button', mSeg).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === 'lexical'))); }
    });
    const searchBtn = h('button', { class: 'btn gray', type: 'button' }, 'Search');
    const answerBtn = h('button', { class: 'btn', type: 'button' }, 'Answer');
    const toolbar = h('div', { class: 'wb-tool' }, sideBtn, wrap, kSel, mSeg, searchBtn, answerBtn);

    // ---- left pane
    const leftTabs = seg([['results', 'Results'], ['history', 'History'], ['dataset', 'Dataset']], WB.left, (v) => { WB.left = v; renderLeft(); }, 'Left pane');
    const leftBody = h('div', { class: 'wb-scroll' });
    const left = h('section', { class: 'wb-pane wb-left', 'aria-label': 'Results' }, h('div', { class: 'pane-head' }, leftTabs), leftBody);

    // ---- viewer
    const vPath = h('div', { class: 'v-path' });
    const vMeta = h('div', { class: 'v-meta' });
    const bounds = h('input', { type: 'checkbox', id: 'wb-bounds' });
    bounds.checked = WB.boundaries;
    bounds.addEventListener('change', () => { WB.boundaries = bounds.checked; store.set('wb.bounds', WB.boundaries); renderViewer(); });
    const legend = h('div', { class: 'v-legend' },
      h('span', null, h('i', { class: 'lg lg-sel' }), 'Selected'),
      h('span', null, h('i', { class: 'lg lg-hit' }), 'Other results'),
      h('span', { class: 'lg-refitem' }, h('i', { class: 'lg lg-ref' }), 'Reference'),
      h('label', { for: 'wb-bounds', class: 'v-toggle' }, bounds, 'Chunk boundaries'));
    const gutter = h('pre', { class: 'v-gutter', 'aria-hidden': 'true' });
    const code = h('pre', { class: 'v-code' });
    const vScroll = h('div', { class: 'v-scroll' }, gutter, code);
    const vEmpty = h('div', { class: 'wb-empty' }, h('div', { class: 'wb-empty-ico', html: svg('files') }), h('h3', null, 'No file open'), h('p', null, 'Search for something, then pick a result. Its file opens here with the retrieved span highlighted.'));
    const viewer = h('section', { class: 'wb-pane wb-viewer', 'aria-label': 'Source file' },
      h('div', { class: 'pane-head v-head' }, vPath, vMeta, legend), vEmpty, vScroll);

    // ---- inspector
    const iTabs = seg([['why', 'Why'], ['answer', 'Answer'], ['prompt', 'Prompt'], ['chunk', 'Chunk']], WB.tab, (v) => { WB.tab = v; store.set('wb.tab', v); renderInspector(); }, 'Inspector');
    const iBody = h('div', { class: 'wb-scroll wb-inspect' });
    const inspector = h('section', { class: 'wb-pane wb-right', 'aria-label': 'Inspector' }, h('div', { class: 'pane-head' }, iTabs), iBody);

    // ---- status bar
    const sIndex = h('span'), sSearch = h('span'), sAnswer = h('span');
    const status = h('footer', { class: 'wb-status' }, h('span', { class: 'led ok', style: 'margin:0' }), sIndex, h('i', { class: 'sep' }), sSearch, h('i', { class: 'sep' }), sAnswer,
      h('span', { class: 'wb-keys' }, h('kbd', null, '↑'), h('kbd', null, '↓'), ' results · ', h('kbd', null, 'Return'), ' search · ', h('kbd', null, '⌘ Return'), ' answer'));
    whenHealth().then((hd) => { sIndex.textContent = `${n0(hd.chunks)} chunks · ${n0(hd.vocabulary)} terms · max ${n0(hd.max_chunk_size)} chars`; });
    function renderStatus() {
      sSearch.textContent = WB.searchMs === null ? 'No search yet' : `${WB.hits.length} results in ${secs(WB.searchMs)} · ${WB.mode === 'lexical' ? 'BM25' : WB.mode}`;
      const a = WB.answers.get(keyOf(WB.q, WB.k, WB.mode));
      sAnswer.textContent = a && a.ms ? `Answer in ${secs(a.ms)}` : 'No answer yet';
    }

    const root = h('div', { class: 'wb' }, toolbar, h('div', { class: 'wb-body' }, left, viewer, inspector), status);

    // ================= actions
    let runId = 0;
    async function runSearch(opts = {}) {
      const q = input.value.trim();
      if (!q) { input.focus(); return false; }
      if (!opts.keepRefs) { WB.refs = null; WB.refQuestion = null; }
      WB.q = q; store.set('wb.q', q);
      const id = ++runId;
      const done = busy(searchBtn, 'Searching…');
      const t0 = performance.now();
      try {
        const body = { query: q, k: WB.k, mode: WB.mode };
        const [hits, bm] = await Promise.all([api('/explore', body), WB.mode === 'lexical' ? api('/learn/bm25', body) : Promise.resolve(null)]);
        if (id !== runId) return false;
        WB.searchMs = performance.now() - t0;
        WB.hits = hits; WB.bm = bm; WB.sel = hits.length ? 0 : -1;
        pushHistory(q, hits.length);
        WB.left = 'results'; setSeg(leftTabs, 'results');
        renderLeft(); renderViewer(); renderInspector(); renderStatus();
        return true;
      } catch (e) { showError(e.message); return false; }
      finally { done(); }
    }
    async function runAnswer() {
      const ok = WB.hits.length && WB.q === input.value.trim() ? true : await runSearch({ keepRefs: true });
      if (!ok) return;
      WB.tab = 'answer'; store.set('wb.tab', 'answer'); setSeg(iTabs, 'answer');
      const key = keyOf(WB.q, WB.k, WB.mode);
      if (WB.answers.has(key) && WB.answers.get(key).text) { renderInspector(); return; }
      const entry = { text: null, ms: null, started: performance.now(), error: null };
      WB.answers.set(key, entry);
      renderInspector();
      const done = busy(answerBtn, 'Answering…');
      try {
        const res = await api('/answer', { query: WB.q, k: WB.k, mode: WB.mode });
        entry.text = res.answer; entry.ms = performance.now() - entry.started;
      } catch (e) { entry.error = e.message; }
      finally { done(); renderInspector(); renderStatus(); }
    }
    function showError(msg) {
      WB.left = 'results'; setSeg(leftTabs, 'results');
      leftBody.replaceChildren(h('div', { class: 'wb-note bad' }, msg));
    }
    function setSeg(box, v) { $$('button', box).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === v))); }
    function select(i) {
      if (i < 0 || i >= WB.hits.length) return;
      WB.sel = i;
      $$('.r-item', leftBody).forEach((el, j) => el.classList.toggle('sel', j === i));
      const cur = $$('.r-item', leftBody)[i];
      if (cur) cur.scrollIntoView({ block: 'nearest' });
      renderViewer(); renderInspector();
    }
    function pushHistory(q, n) {
      WB.history = [{ q, k: WB.k, mode: WB.mode, n, t: Date.now() }, ...WB.history.filter((x) => !(x.q === q && x.k === WB.k && x.mode === WB.mode))].slice(0, 40);
      store.set('wb.history', WB.history);
    }

    // ================= left pane
    function renderLeft() {
      if (WB.left === 'results') return renderResults();
      if (WB.left === 'history') return renderHistory();
      return renderDataset();
    }
    function renderResults() {
      const items = [];
      if (WB.refQuestion) {
        const found = WB.refs.filter((r) => WB.hits.some((x) => iou(r, x) >= 0.05)).length;
        items.push(h('div', { class: 'wb-note' }, h('b', null, 'Dataset question. '), `${found} of ${WB.refs.length} reference sources found in the top ${WB.k}. Green underlines mark them in the viewer. Open a reference to see where the answer really is:`,
          h('div', { class: 'ref-links' }, WB.refs.map((r) => {
            const hitIt = WB.hits.some((x) => iou(r, x) >= 0.05);
            return h('button', { type: 'button', class: 'ref-link', onclick: () => openSource(r) }, h('span', { class: 'tag ' + (hitIt ? 'ok' : 'bad') }, hitIt ? 'found' : 'missed'), h('span', { class: 'path' }, r.file_path.replace('data/raw/vllm-0.10.1/', '')), h('span', { class: 'r-meta' }, `[${r.first_character_index}:${r.last_character_index}]`));
          }))));
      }
      if (!WB.hits.length) {
        items.push(WB.searchMs === null
          ? h('div', { class: 'wb-empty small' }, h('h3', null, 'Start with a question'), h('p', null, 'Try one of these:'),
            h('div', { class: 'chips', style: 'justify-content:center' }, ['How do I load a LoRA adapter at runtime?', 'What does enable_prefix_caching do?', 'How is the KV cache block size chosen?'].map((s) => h('button', { class: 'chip', type: 'button', onclick: () => { input.value = s; runSearch(); } }, s))))
          : h('div', { class: 'wb-note' }, 'No chunk shares a term with this question. Name an identifier, a file or a feature.'));
        leftBody.replaceChildren(...items);
        return;
      }
      const max = Math.max(...WB.hits.map((x) => x.score), 1e-9);
      WB.hits.forEach((hit, i) => {
        const match = refMatch(hit);
        const name = hit.file_path.split('/').pop();
        const dir = hit.file_path.replace('data/raw/vllm-0.10.1/', '').split('/').slice(0, -1).join('/');
        const el = h('button', { type: 'button', class: 'r-item' + (i === WB.sel ? ' sel' : ''), onclick: () => select(i) },
          h('span', { class: 'r-rank' }, i + 1),
          h('span', { class: 'r-main' },
            h('span', { class: 'r-name' }, h('span', { class: 'tag ' + kindOf(hit.file_path) }, kindOf(hit.file_path)), name, match ? h('span', { class: 'tag ok' }, 'reference') : null),
            h('span', { class: 'r-dir' }, dir || '.'),
            h('span', { class: 'r-bar' }, h('i', { style: `width:${(hit.score / max) * 100}%` })),
            h('span', { class: 'r-meta' }, `score ${f2(hit.score)} · [${hit.first_character_index}:${hit.last_character_index}]`)));
        items.push(el);
      });
      leftBody.replaceChildren(...items);
    }
    function renderHistory() {
      if (!WB.history.length) { leftBody.replaceChildren(h('div', { class: 'wb-empty small' }, h('h3', null, 'No history yet'), h('p', null, 'Every search you run is kept here, on this browser.'))); return; }
      leftBody.replaceChildren(
        ...WB.history.map((x) => h('button', { type: 'button', class: 'r-item', onclick: () => { input.value = x.q; WB.k = x.k; kSel.value = String(x.k); runSearch(); } },
          h('span', { class: 'r-main' }, h('span', { class: 'r-q' }, x.q), h('span', { class: 'r-meta' }, `${x.mode === 'lexical' ? 'BM25' : x.mode} · top ${x.k} · ${x.n} results · ${new Date(x.t).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`)))),
        h('div', { style: 'padding:10px 12px' }, h('button', { class: 'btn plain', type: 'button', onclick: () => { WB.history = []; store.set('wb.history', []); renderHistory(); } }, 'Clear history')));
    }
    async function renderDataset() {
      const box = h('div', { class: 'ds' });
      leftBody.replaceChildren(box);
      let names = [];
      try { names = await api('/datasets'); } catch (e) { box.replaceChildren(h('div', { class: 'wb-note bad' }, e.message)); return; }
      if (WB.left !== 'dataset') return;
      if (!names.length) { box.replaceChildren(h('div', { class: 'wb-note' }, 'No datasets in data/datasets/AnsweredQuestions.')); return; }
      if (!names.includes(WB.ds)) WB.ds = names[0];
      const pretty = (n) => n.replace(/^dataset_|_public\.json$|\.json$/g, '').replace(/^./, (c) => c.toUpperCase());
      const dsSeg = seg(names.map((n) => [n, pretty(n)]), WB.ds, (v) => { WB.ds = v; store.set('wb.ds', v); WB.dsData = null; renderDataset(); }, 'Dataset');
      const runBtn = h('button', { class: 'btn', type: 'button' }, WB.dsData ? 'Run again' : 'Run');
      const list = h('div');
      const fSeg = seg([['all', 'All'], ['miss', 'Missed'], ['partial', 'Partial']], WB.dsFilter, (v) => { WB.dsFilter = v; drawList(); }, 'Filter');
      const tiles = h('div', { class: 'ds-tiles' });
      runBtn.addEventListener('click', async () => {
        const done = busy(runBtn, 'Running…');
        try { WB.dsData = await api('/evaluate', { dataset: WB.ds, k: Math.max(WB.k, 5), mode: WB.mode }); drawTiles(); drawList(); }
        catch (e) { list.replaceChildren(h('div', { class: 'wb-note bad' }, e.message)); }
        finally { done(); }
      });
      const target = /code/i.test(WB.ds) ? 0.5 : /doc/i.test(WB.ds) ? 0.8 : null;
      function drawTiles() {
        if (!WB.dsData) { tiles.replaceChildren(); return; }
        tiles.replaceChildren(...Object.entries(WB.dsData.recall).map(([kk, v]) => h('div', { class: 'ds-tile' + (kk === '5' && target !== null ? (v >= target ? ' ok' : ' bad') : '') }, h('b', null, f3(v)), h('span', null, `@${kk}`))));
      }
      function drawList() {
        if (!WB.dsData) { list.replaceChildren(h('div', { class: 'wb-note' }, `Runs every question in ${pretty(WB.ds)} through your retriever with the toolbar’s mode${target !== null ? `. Target at @5 is ${f2(target)}` : ''}.`)); return; }
        const at5 = (q) => q.recall['5'] ?? 0;
        const qs = WB.dsData.questions.filter((q) => (WB.dsFilter === 'miss' ? at5(q) === 0 : WB.dsFilter === 'partial' ? at5(q) > 0 && at5(q) < 1 : true));
        list.replaceChildren(...(qs.length ? qs.map((q) => {
          const r = at5(q);
          return h('button', { type: 'button', class: 'r-item' + (WB.refQuestion === q.question_id ? ' sel' : ''), onclick: () => {
            WB.refs = q.references.map((x) => x.source); WB.refQuestion = q.question_id;
            input.value = q.question; runSearch({ keepRefs: true });
          } }, h('span', { class: 'pill ' + (r >= 0.999 ? 'ok' : r > 0 ? 'mid' : 'bad') }, f2(r)), h('span', { class: 'r-main' }, h('span', { class: 'r-q' }, q.question)));
        }) : [h('div', { class: 'wb-note' }, 'No question matches this filter.')]));
      }
      box.replaceChildren(h('div', { class: 'ds-head' }, dsSeg, runBtn), tiles, h('div', { class: 'ds-head' }, fSeg), list);
      drawTiles(); drawList();
    }

    // ================= viewer
    let viewToken = 0;
    async function renderViewer() {
      const hit = WB.hits[WB.sel];
      const token = ++viewToken;
      if (!hit) { vEmpty.hidden = false; vScroll.hidden = true; vPath.replaceChildren(); vMeta.textContent = ''; return; }
      vEmpty.hidden = true; vScroll.hidden = false;
      vPath.replaceChildren(pathEl(hit.file_path));
      vMeta.textContent = 'Opening…';
      let text;
      try {
        if (!fileCache.has(hit.file_path)) fileCache.set(hit.file_path, (await api('/file?path=' + encodeURIComponent(hit.file_path))).text);
        text = fileCache.get(hit.file_path);
      } catch (e) { vMeta.textContent = e.message; return; }
      let chunkRanges = [];
      if (WB.boundaries && health) {
        try {
          const d = await api('/learn/chunk', { path: hit.file_path, max_chunk_size: health.max_chunk_size, min_chunk_size: Math.min(800, health.max_chunk_size) });
          chunkRanges = d.chunks.map((c, i) => ({ a: c.first_character_index, b: c.last_character_index, cls: i % 2 ? 'cb-b' : 'cb-a' }));
        } catch { /* boundaries are optional */ }
      }
      if (token !== viewToken) return;
      const ranges = [...chunkRanges];
      WB.hits.forEach((x, i) => { if (x.file_path === hit.file_path) ranges.push({ a: x.first_character_index, b: x.last_character_index, cls: i === WB.sel ? 'hl-sel' : 'hl-hit' }); });
      (WB.refs || []).forEach((r) => { if (r.file_path === hit.file_path) ranges.push({ a: r.first_character_index, b: r.last_character_index, cls: 'hl-ref' }); });
      const pts = new Set([0, text.length]);
      ranges.forEach((r) => { pts.add(Math.max(0, Math.min(text.length, r.a))); pts.add(Math.max(0, Math.min(text.length, r.b))); });
      const sorted = [...pts].sort((x, y) => x - y);
      const nodes = [];
      for (let i = 0; i < sorted.length - 1; i++) {
        const a = sorted[i], b = sorted[i + 1];
        if (a === b) continue;
        const cls = ranges.filter((r) => r.a <= a && r.b >= b).map((r) => r.cls);
        nodes.push(cls.length ? h('span', { class: cls.join(' ') }, text.slice(a, b)) : text.slice(a, b));
      }
      code.replaceChildren(...nodes);
      const lines = text.split('\n').length;
      gutter.textContent = Array.from({ length: lines }, (_, i) => i + 1).join('\n');
      const a = hit.first_character_index, b = hit.last_character_index;
      const l1 = text.slice(0, a).split('\n').length, l2 = l1 + text.slice(a, b).split('\n').length - 1;
      vMeta.textContent = `Result ${WB.sel + 1} · lines ${l1}–${l2} · characters ${n0(a)}–${n0(b)} · ${n0(b - a)} wide · file is ${n0(text.length)} characters`;
      legend.querySelector('.lg-refitem').hidden = !(WB.refs && WB.refs.some((r) => r.file_path === hit.file_path));
      requestAnimationFrame(() => {
        const first = $('.hl-sel', code);
        if (first) vScroll.scrollTop = Math.max(0, first.offsetTop - vScroll.clientHeight / 3);
      });
    }

    // ================= inspector
    function renderInspector() {
      const hit = WB.hits[WB.sel];
      if (WB.tab === 'answer') return iBody.replaceChildren(inspectAnswer());
      if (WB.tab === 'prompt') return iBody.replaceChildren(inspectPrompt());
      if (!hit) return iBody.replaceChildren(h('div', { class: 'wb-empty small' }, h('h3', null, 'Nothing selected'), h('p', null, 'Pick a result to inspect it.')));
      if (WB.tab === 'chunk') return iBody.replaceChildren(inspectChunk(hit));
      return iBody.replaceChildren(inspectWhy(hit));
    }
    function inspectWhy(hit) {
      if (WB.mode !== 'lexical' || !WB.bm) return h('div', { class: 'wb-note' }, `This result was ranked by ${WB.mode} search, which compares embeddings, so there is no per-term breakdown. Switch to BM25 to see one.`);
      const d = WB.bm;
      const bh = d.hits.find((x) => sameSpan(x, hit));
      if (!bh) return h('div', { class: 'wb-note' }, 'No breakdown found for this result. Run the search again.');
      const colorOf = new Map(d.terms.map((t, i) => [t.term, TERM_COLORS[i % TERM_COLORS.length]]));
      const calc = h('div', { class: 'calc sm' });
      const rows = bh.terms.map((t) => {
        const tr = h('tr', { class: 'click', tabindex: '0' }, h('td', null, h('i', { class: 'swatch', style: `background:${colorOf.get(t.term)}` }), h('code', null, t.term)), h('td', null, String(t.tf)), h('td', null, f2(t.contribution)));
        const show = () => { $$('tr', tbody).forEach((x) => x.classList.toggle('sel', x === tr)); drawCalc(calc, d, bh, t); };
        tr.addEventListener('click', show);
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') show(); });
        return [tr, show];
      });
      const tbody = h('tbody', null, rows.map((r) => r[0]));
      const missing = d.terms.filter((t) => !bh.terms.some((x) => x.term === t.term));
      const out = h('div', { class: 'insp' },
        h('div', { class: 'insp-score' }, h('b', null, f2(bh.score)), h('span', null, `BM25 score, rank ${WB.sel + 1} of ${WB.hits.length}`)),
        h('div', { class: 'stack' }, bh.terms.map((t) => h('i', { style: `flex:${t.contribution} 1 0;background:${colorOf.get(t.term)}` }))),
        h('table', { class: 'terms' }, h('thead', null, h('tr', null, h('th', null, 'Term'), h('th', null, 'tf'), h('th', null, 'Added'))), tbody),
        missing.length ? h('p', { class: 'hint', style: 'margin:0' }, 'Not in this chunk: ', missing.map((t, i) => [i ? ', ' : '', h('code', null, t.term)])) : null,
        h('div', { class: 'field-label' }, 'How the selected term was scored'),
        calc,
        h('p', { class: 'hint', style: 'margin:0' }, `This chunk has ${n0(bh.length)} terms, the average is ${n0(Math.round(d.average_length))}. The path is indexed twice in front of the text, so words in the path count too.`));
      if (rows.length) rows[0][1]();
      return out;
    }
    function inspectAnswer() {
      const key = keyOf(WB.q, WB.k, WB.mode);
      const a = WB.answers.get(key);
      if (!WB.q) return h('div', { class: 'wb-note' }, 'Search for something first, then press Answer.');
      if (!a) return h('div', { class: 'insp' }, h('p', { class: 'hint', style: 'margin:0' }, `Qwen3-0.6B will answer “${WB.q}” from the top ${WB.k} sources.`), h('button', { class: 'btn', type: 'button', onclick: runAnswer }, 'Generate answer'));
      if (a.error) return h('div', { class: 'wb-note bad' }, a.error);
      const meta = h('span');
      const text = h('p', null, a.text !== null ? a.text : h('span', { class: 'typing' }, h('i'), h('i'), h('i')));
      if (a.text === null) {
        const id = setInterval(() => { if (!meta.isConnected || a.text !== null) { clearInterval(id); return; } meta.textContent = `· ${((performance.now() - a.started) / 1000).toFixed(1)} s`; }, 100);
      } else meta.textContent = `· ${secs(a.ms)}`;
      return h('div', { class: 'insp' },
        h('div', { class: 'answer-card flat' }, h('div', { class: 'who' }, icon('gen', 'var(--c-gen)'), 'Qwen3-0.6B ', meta), text),
        h('p', { class: 'hint', style: 'margin:0' }, `Question: ${WB.q}`),
        h('p', { class: 'hint', style: 'margin:0' }, 'Greedy decoding, so the same question and sources always give the same answer. Open the Prompt tab to see exactly what the model read.'));
    }
    function inspectPrompt() {
      if (!WB.q) return h('div', { class: 'wb-note' }, 'Search for something first.');
      const key = keyOf(WB.q, WB.k, WB.mode);
      const p = WB.prompts.get(key);
      if (!p) {
        const btn = h('button', { class: 'btn', type: 'button' }, 'Build the prompt');
        const msg = h('span', { class: 'hint' });
        btn.addEventListener('click', async () => {
          const done = busy(btn, 'Building…');
          const stop = ticker(msg, 'Loading the tokenizer if needed… ');
          try { WB.prompts.set(key, await api('/learn/prompt', { query: WB.q, k: WB.k, mode: WB.mode })); stop(); renderInspector(); }
          catch (e) { stop(); msg.textContent = e.message; }
          finally { done(); }
        });
        return h('div', { class: 'insp' }, h('p', { class: 'hint', style: 'margin:0' }, 'See the exact text Qwen3 receives for this question: the system message, the sources that fit in the 3,000-token budget, and the question.'), h('div', { class: 'row' }, btn, msg));
      }
      const used = p.sources.filter((s) => s.included).reduce((acc, s) => acc + s.tokens, 0);
      const parts = p.prompt.split(/(<\|im_start\|>\w+|<\|im_end\|>)/g).map((x, i) => (i % 2 ? h('span', { class: 'role' }, x) : x));
      return h('div', { class: 'insp' },
        h('div', { class: 'insp-score' }, h('b', null, `${n0(used)}`), h('span', null, `of ${n0(p.budget)} source tokens · ${n0(p.prompt_tokens)} in the whole prompt`)),
        h('div', { class: 'budget' }, p.sources.filter((s) => s.included).map((s) => h('i', { style: `width:${Math.min(100, (s.tokens / p.budget) * 100)}%` }))),
        h('table', { class: 'terms' }, h('tbody', null, p.sources.map((s, i) => h('tr', null, h('td', null, `${i + 1}`), h('td', { style: 'overflow-wrap:anywhere' }, s.file_path.split('/').pop()), h('td', null, `${s.tokens}`), h('td', null, h('span', { class: 'tag ' + (s.included ? 'ok' : 'bad') }, s.included ? 'in' : 'out')))))),
        h('pre', { class: 'code' }, parts));
    }
    function inspectChunk(hit) {
      const copy = h('button', { class: 'btn gray', type: 'button' }, 'Copy as MinimalSource');
      copy.addEventListener('click', async () => {
        const json = JSON.stringify({ file_path: hit.file_path, first_character_index: hit.first_character_index, last_character_index: hit.last_character_index }, null, 2);
        try { await navigator.clipboard.writeText(json); copy.textContent = 'Copied'; } catch { copy.textContent = 'Copy failed'; }
        setTimeout(() => { copy.textContent = 'Copy as MinimalSource'; }, 1400);
      });
      const best = WB.refs ? Math.max(0, ...WB.refs.map((r) => iou(r, hit))) : null;
      return h('div', { class: 'insp' },
        h('div', { class: 'kv' },
          h('span', null, 'Rank'), h('b', null, `${WB.sel + 1} of ${WB.hits.length}`),
          h('span', null, 'Score'), h('b', null, f3(hit.score)),
          h('span', null, 'Strategy'), h('b', null, kindOf(hit.file_path) === 'py' ? 'Python (ast)' : 'Markdown / text'),
          h('span', null, 'Span'), h('b', null, `[${hit.first_character_index}:${hit.last_character_index}]`),
          h('span', null, 'Width'), h('b', null, `${n0(hit.last_character_index - hit.first_character_index)} of 2,000 allowed`),
          best !== null ? [h('span', null, 'Best IoU with a reference'), h('b', { class: best >= 0.05 ? 'ok' : 'bad' }, `${f3(best)} ${best >= 0.05 ? '(counts)' : '(does not count)'}`)] : null),
        h('div', { class: 'field-label' }, 'file_path, exactly as the grader compares it'),
        h('code', { class: 'code', style: 'display:block;max-height:none' }, hit.file_path),
        copy,
        h('div', { class: 'field-label' }, 'Chunk text'),
        h('pre', { class: 'code' }, hit.text));
    }

    // ================= wiring
    searchBtn.addEventListener('click', () => runSearch());
    answerBtn.addEventListener('click', runAnswer);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); if (e.metaKey || e.ctrlKey) runAnswer(); else runSearch(); }
      if (e.key === 'ArrowDown' && WB.hits.length) { e.preventDefault(); input.blur(); select(Math.min(WB.sel + 1, WB.hits.length - 1)); }
    });
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); input.focus(); input.select(); return; }
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
      if (typing) return;
      if (e.key === 'ArrowDown' || e.key === 'j') { e.preventDefault(); select(Math.min(WB.sel + 1, WB.hits.length - 1)); }
      if (e.key === 'ArrowUp' || e.key === 'k') { e.preventDefault(); select(Math.max(WB.sel - 1, 0)); }
    };
    document.addEventListener('keydown', onKey);
    root.cleanup = () => document.removeEventListener('keydown', onKey);

    renderLeft(); renderViewer(); renderInspector(); renderStatus();
    if (!WB.q) requestAnimationFrame(() => input.focus());
    return root;
  }

  function drawCalc(box, d, hit, t) {
    const term = d.terms.find((x) => x.term === t.term);
    const N = d.documents, df = term.document_frequency, k1 = d.k1, b = d.b;
    const idf = Math.log((N - df + 0.5) / (df + 0.5) + 1);
    const norm = 1 - b + b * hit.length / d.average_length;
    const w = idf * t.tf * (k1 + 1) / (t.tf + k1 * norm);
    box.replaceChildren(
      h('div', null, 'idf    = ln((', n0(N), ' − ', n0(df), ' + 0.5) / (', n0(df), ' + 0.5) + 1) = ', h('b', null, f3(idf))),
      h('div', null, `norm   = 1 − ${b} + ${b} · ${n0(hit.length)} / ${f2(d.average_length)} = `, h('b', null, f3(norm))),
      h('div', null, `weight = ${f3(idf)} · ${t.tf} · ${k1 + 1} / (${t.tf} + ${k1} · ${f3(norm)}) = `, h('b', null, f3(w))),
      h('div', null, `added  = weight × ${term.count} = `, h('b', null, f3(w * term.count))));
  }

  // ---------------------------------------------------------------- index
  function pageIndex() {
    const statsBox = h('div', { class: 'stats' });
    const draw = (hd) => statsBox.replaceChildren(
      stat('Chunks', n0(hd.chunks)), stat('Files', n0(hd.files)), stat('Vocabulary', n0(hd.vocabulary) + ' terms'),
      stat('Max chunk size', n0(hd.max_chunk_size)), stat('Embeddings', hd.semantic ? hd.semantic.split('/').pop() : 'Not built'), stat('Answer model', hd.model.split('/').pop()));
    whenHealth().then(draw);
    let full = false;
    const size = slider('Max chunk size', 100, 2000, 50, health ? health.max_chunk_size : 2000, 'var(--accent)', () => {});
    const kind = seg([['inc', 'Only changed files'], ['full', 'Full rebuild']], 'inc', (v) => { full = v === 'full'; }, 'Rebuild type');
    const emb = h('input', { type: 'checkbox', id: 'ix-emb' });
    const runBtn = h('button', { class: 'btn', type: 'button' }, 'Rebuild index');
    const cacheBtn = h('button', { class: 'btn gray', type: 'button' }, 'Clear query cache');
    const msg = h('span', { class: 'hint' });
    const err = errorLine();
    runBtn.addEventListener('click', async () => {
      err.textContent = '';
      const sz = Number(size.input.value);
      let incremental = !full;
      let note = '';
      if (incremental && health && sz !== health.max_chunk_size) { incremental = false; note = 'The chunk size changed, so this is a full rebuild. '; }
      const done = busy(runBtn, 'Rebuilding…');
      const stop = ticker(msg, note + 'Running for ');
      try {
        const r = await api('/index', { max_chunk_size: sz, incremental, semantic: emb.checked });
        stop();
        msg.textContent = `Done in ${r.seconds} s: ${n0(r.chunks)} chunks from ${n0(r.files)} files. Cached queries were cleared.`;
        fileCache.clear();
        draw(await loadHealth());
      } catch (e) { stop(); msg.textContent = ''; err.textContent = e.message; }
      finally { done(); }
    });
    cacheBtn.addEventListener('click', async () => {
      err.textContent = '';
      try { await api('/cache/clear', {}); msg.textContent = 'Query cache cleared.'; } catch (e) { err.textContent = e.message; }
    });
    return h('div', { class: 'page' },
      pageHead('index', 'var(--c-corpus)', 'Lab', 'Index', 'The index lives in data/processed/. Rebuild it after changing the corpus or the chunking settings.'),
      statsBox,
      h('div', { class: 'panel' },
        h('div', { class: 'panel-title' }, 'Rebuild'),
        h('div', { class: 'row', style: 'gap:24px;align-items:flex-end' }, size, kind),
        h('p', { class: 'hint', style: 'margin:0' }, 'Only changed files hashes every file and re-chunks the new or modified ones, which is the incremental indexing bonus. A full rebuild takes about 5 seconds.'),
        h('label', { class: 'row', style: 'gap:10px;cursor:pointer;align-items:flex-start', for: 'ix-emb' }, emb, h('span', null, 'Also build MiniLM embeddings', h('br'), h('span', { class: 'hint' }, 'Turns on Semantic and Hybrid search. Takes about 1.5 minutes and needs sentence-transformers installed.'))),
        h('div', { class: 'row' }, runBtn, cacheBtn, msg),
        err));
  }

  // ================================================================== router
  const routes = { overview: pageOverview, chunking: pageChunking, tokenizing: pageTokenizing, ranking: pageRanking, prompt: pagePrompt, generating: pageGenerating, recall: pageRecall, workbench: pageWorkbench, index: pageIndex };
  const ALIASES = { ask: 'workbench', evaluate: 'workbench' };
  let current = null;
  function route() {
    const raw = location.hash.replace(/^#\/?/, '');
    const name = routes[raw] ? raw : ALIASES[raw] || 'overview';
    const main = $('#main');
    if (current && current.cleanup) current.cleanup();
    current = routes[name]();
    main.replaceChildren(current);
    main.scrollTop = 0;
    const isWb = name === 'workbench';
    main.classList.toggle('full', isWb);
    $('.app').classList.toggle('side-off', isWb && store.get('wb.sideoff', false));
    if (isWb) closeSheet();
    $$('.side-nav a').forEach((a) => a.setAttribute('aria-current', a.dataset.route === name ? 'page' : 'false'));
    document.title = `${TITLES[name]} · RAG Workbench`;
  }
  window.addEventListener('hashchange', route);
  loadHealth();
  route();
})();
