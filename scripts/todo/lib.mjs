// Shared code for the task-file system under docs/todo/ (see docs/todo/README.md).
// Node built-ins only. The frontmatter is a deliberately small YAML subset:
//   key: value                 bare scalar, "double-quoted" (JSON escapes), 'single-quoted', null or ~
//   key: []  /  key: [a, "b"]  inline list of scalars
//   key:                       block list, one "  - item" per line
// Anything else in the frontmatter is reported as an error rather than guessed at.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const TODO_DIR = 'docs/todo';
export const DONE_DIR = 'docs/todo/done';

// Order here is the order of the sections in the generated TODO.md.
export const SECTIONS = [
  { status: 'now', heading: 'Now' },
  { status: 'waiting-sam', heading: 'Waiting on Sam' },
  { status: 'scheduled', heading: 'Scheduled (by due date)' },
  { status: 'next', heading: 'Next' },
  { status: 'idea', heading: 'Ideas' },
  // Keep this heading stable so agents can identify deferred failures.
  { status: 'known-failure', heading: 'Known non-blocking failures — check here BEFORE diagnosing a red suite' },
];
export const STATUSES = [...SECTIONS.map((s) => s.status), 'done'];
export const AREAS = ['billing', 'ci', 'data', 'infra', 'outreach', 'process', 'product', 'security'];
export const OWNERS = ['sam', 'agent'];
export const FIELDS = ['title', 'status', 'area', 'due', 'updated', 'owner', 'brief', 'refs', 'test'];
export const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function isIsoDate(value) {
  if (typeof value !== 'string' || !DATE_RE.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

function parseScalar(raw) {
  const v = raw.trim();
  if (v === '' || v === 'null' || v === '~') return null;
  if (v.startsWith('"')) return JSON.parse(v);
  if (v.startsWith("'")) {
    if (!v.endsWith("'") || v.length < 2) throw new Error(`unterminated single-quoted value: ${v}`);
    return v.slice(1, -1).replace(/''/g, "'");
  }
  return v;
}

function splitInlineList(inner) {
  const items = [];
  let cur = '';
  let quote = null;
  for (let i = 0; i < inner.length; i++) {
    const ch = inner[i];
    if (quote) {
      cur += ch;
      if (ch === '\\' && quote === '"') cur += inner[++i] ?? '';
      else if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
      cur += ch;
    } else if (ch === ',') {
      items.push(cur);
      cur = '';
    } else cur += ch;
  }
  if (cur.trim()) items.push(cur);
  return items.map(parseScalar);
}

// Returns { data, body, errors }. data is null when there is no frontmatter block at all.
export function parseFrontmatter(text) {
  const lines = text.split('\n');
  if (lines[0] !== '---') return { data: null, body: text, errors: ['missing frontmatter (file must start with a "---" line)'] };
  const end = lines.indexOf('---', 1);
  if (end === -1) return { data: null, body: text, errors: ['unterminated frontmatter (no closing "---" line)'] };
  const data = {};
  const errors = [];
  let listKey = null;
  for (let i = 1; i < end; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    const item = /^\s+-\s?(.*)$/.exec(line);
    if (item && listKey) {
      try {
        data[listKey].push(parseScalar(item[1]));
      } catch (err) {
        errors.push(`line ${i + 1}: ${err.message}`);
      }
      continue;
    }
    const kv = /^([A-Za-z_][\w-]*):(?:\s(.*))?$/.exec(line);
    if (!kv) {
      errors.push(`line ${i + 1}: cannot parse "${line}"`);
      listKey = null;
      continue;
    }
    const [, key, rawValue = ''] = kv;
    if (key in data) errors.push(`line ${i + 1}: duplicate key "${key}"`);
    const value = rawValue.trim();
    listKey = null;
    try {
      if (value === '') {
        data[key] = [];
        listKey = key;
      } else if (value.startsWith('[')) {
        if (!value.endsWith(']')) throw new Error(`unterminated inline list for "${key}"`);
        data[key] = splitInlineList(value.slice(1, -1));
      } else data[key] = parseScalar(value);
    } catch (err) {
      errors.push(`line ${i + 1}: ${err.message}`);
    }
  }
  // An empty block list ("key:" with no items) means null for scalar fields.
  for (const key of Object.keys(data)) if (key !== 'refs' && Array.isArray(data[key]) && data[key].length === 0) data[key] = null;
  const body = lines.slice(end + 1).join('\n');
  return { data, body, errors };
}

const quote = (v) => JSON.stringify(v);

export function serializeFrontmatter(data) {
  const out = ['---'];
  out.push(`title: ${quote(data.title)}`);
  out.push(`status: ${data.status}`);
  out.push(`area: ${data.area}`);
  out.push(`due: ${data.due ?? 'null'}`);
  out.push(`updated: ${data.updated}`);
  out.push(`owner: ${data.owner}`);
  out.push(`brief: ${quote(data.brief)}`);
  if (data.refs?.length) {
    out.push('refs:');
    for (const ref of data.refs) out.push(`  - ${quote(ref)}`);
  } else out.push('refs: []');
  out.push(`test: ${data.test == null ? 'null' : quote(data.test)}`);
  out.push('---');
  return out.join('\n') + '\n';
}

export function expectedRelPath(data, slug) {
  const base = data.status === 'done' ? DONE_DIR : TODO_DIR;
  return `${base}/${data.area}/${slug}.md`;
}

function walk(dir) {
  const out = [];
  let names;
  try {
    names = readdirSync(dir);
  } catch {
    return out;
  }
  for (const name of names.sort()) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (name.endsWith('.md')) out.push(full);
  }
  return out;
}

// Task files are every *.md under docs/todo/ except top-level docs (README.md and friends).
export function listTaskFiles(root = REPO_ROOT) {
  const dir = path.join(root, TODO_DIR);
  return walk(dir).filter((full) => path.dirname(full) !== dir);
}

export function validateTask(task) {
  const errors = [...task.parseErrors];
  const d = task.data;
  if (!d) return errors;
  for (const key of Object.keys(d)) if (!FIELDS.includes(key)) errors.push(`unknown field "${key}"`);
  for (const key of FIELDS) if (!(key in d)) errors.push(`missing field "${key}"`);
  if (typeof d.title !== 'string' || !d.title.trim()) errors.push('title must be a non-empty string');
  if (!STATUSES.includes(d.status)) errors.push(`unknown status "${d.status}" (allowed: ${STATUSES.join(', ')})`);
  if (!AREAS.includes(d.area)) errors.push(`unknown area "${d.area}" (allowed: ${AREAS.join(', ')})`);
  if (d.due !== null && d.due !== undefined && !isIsoDate(d.due)) errors.push(`due "${d.due}" is not a valid YYYY-MM-DD date or null`);
  if (!isIsoDate(d.updated)) errors.push(`updated "${d.updated}" is not a valid YYYY-MM-DD date`);
  if (!OWNERS.includes(d.owner)) errors.push(`unknown owner "${d.owner}" (allowed: ${OWNERS.join(', ')})`);
  if (typeof d.brief !== 'string' || !d.brief.trim()) errors.push('brief must be a non-empty string');
  else if (d.brief.includes('\n')) errors.push('brief must be one line');
  if ('refs' in d && !Array.isArray(d.refs)) errors.push('refs must be a list');
  if (d.status === 'scheduled' && !d.due) errors.push('status "scheduled" needs a due date');
  if (d.status === 'known-failure' && (typeof d.test !== 'string' || !d.test.trim())) errors.push('status "known-failure" needs the exact failing test in "test"');
  if (d.test != null && typeof d.test !== 'string') errors.push('test must be a string or null');
  if (!SLUG_RE.test(task.slug)) errors.push(`file name "${task.slug}.md" is not a kebab-case slug`);
  if (!task.body.trim()) errors.push('body is empty (needs at least the What / Why / Next summary)');
  return errors;
}

export function loadTasks(root = REPO_ROOT) {
  return listTaskFiles(root).map((full) => {
    const rel = path.relative(root, full).split(path.sep).join('/');
    const text = readFileSync(full, 'utf8');
    const { data, body, errors } = parseFrontmatter(text);
    const task = { full, rel, slug: path.basename(full, '.md'), data, body, parseErrors: errors };
    task.errors = validateTask(task);
    return task;
  });
}

const byDueThenTitle = (a, b) =>
  (a.data.due ?? '9999-99-99').localeCompare(b.data.due ?? '9999-99-99') || a.data.title.localeCompare(b.data.title);
const byAreaThenDue = (a, b) => a.data.area.localeCompare(b.data.area) || byDueThenTitle(a, b);

function renderLine(task, status) {
  const d = task.data;
  const parts = [`- [ ] ${d.title} — ${d.brief}`];
  if (d.due) parts.push(`due ${d.due}`);
  if (status === 'known-failure' && d.test) parts.push(`test \`${d.test}\``);
  if (d.owner === 'sam' && status !== 'waiting-sam') parts.push('owner sam');
  parts.push(`_${d.area}_`);
  parts.push(`[details](${task.rel})`);
  return parts.join(' · ');
}

export function renderTodo(tasks) {
  const open = tasks.filter((t) => t.data.status !== 'done');
  const doneCount = tasks.length - open.length;
  const lines = [
    '# TODO — Claude Indicator',
    '',
    '> **Generated** by `node scripts/todo/build.mjs` from one file per task under [`docs/todo/`](docs/todo/README.md). Do not edit this file by hand: edit or add the task file, rebuild, and commit both in one commit.',
    '> **Find tasks:** `node scripts/todo/query.mjs --status now` · `--area ci` · `--owner sam` · `--due-before 2026-10-15` · `--test <name>` · `--grep <text>`. Rules: [docs/todo/README.md](docs/todo/README.md). Finished work: `docs/todo/done/` and [TODO-archive.md](TODO-archive.md).',
    `> ${open.length} open tasks · ${doneCount} done · machine-readable list: [docs/todo/index.json](docs/todo/index.json)`,
    '',
  ];
  for (const { status, heading } of SECTIONS) {
    const group = open.filter((t) => t.data.status === status);
    group.sort(status === 'scheduled' ? byDueThenTitle : byAreaThenDue);
    lines.push(`## ${heading}`, '');
    if (!group.length) lines.push('_None._');
    for (const task of group) lines.push(renderLine(task, status));
    lines.push('');
  }
  return lines.join('\n');
}

export function renderIndex(tasks) {
  const rows = [...tasks]
    .sort((a, b) => a.rel.localeCompare(b.rel))
    .map((t) => ({
      path: t.rel,
      slug: t.slug,
      title: t.data.title,
      status: t.data.status,
      area: t.data.area,
      due: t.data.due ?? null,
      updated: t.data.updated,
      owner: t.data.owner,
      brief: t.data.brief,
      refs: t.data.refs ?? [],
      test: t.data.test ?? null,
    }));
  return JSON.stringify(rows, null, 2) + '\n';
}
