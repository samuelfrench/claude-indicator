#!/usr/bin/env node
// Look up task files under docs/todo/ (reads the files themselves, so it is never stale).
//
//   node scripts/todo/query.mjs --status now,waiting-sam      comma-separated lists allowed
//   node scripts/todo/query.mjs --area ci --owner agent
//   node scripts/todo/query.mjs --due-before 2026-10-15       due on or before that date
//   node scripts/todo/query.mjs --test widget             substring of a known failure's test name
//   node scripts/todo/query.mjs --grep "beta"            case-insensitive, title/brief/refs/test/body
//   --all    include done tasks (default: hidden unless --status names done)
//   --json   print the matching frontmatter as JSON instead of lines
//   --root <dir>
//
// Output: one line per task, "path — title — status — due", sorted by due date (undated last).
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { REPO_ROOT, isIsoDate, loadTasks } from './lib.mjs';

const VALUE_FLAGS = ['--status', '--area', '--owner', '--due-before', '--test', '--grep', '--root'];

export function parseArgs(argv) {
  const opts = { all: false, json: false, root: REPO_ROOT };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--all') opts.all = true;
    else if (arg === '--json') opts.json = true;
    else if (VALUE_FLAGS.includes(arg)) {
      const value = argv[++i];
      if (value === undefined) throw new Error(`${arg} needs a value`);
      const key = arg.slice(2).replace(/-(\w)/g, (_, c) => c.toUpperCase());
      opts[key] = key === 'root' ? path.resolve(value) : value;
    } else throw new Error(`unknown argument ${arg}`);
  }
  if (opts.dueBefore && !isIsoDate(opts.dueBefore)) throw new Error(`--due-before needs YYYY-MM-DD, got ${opts.dueBefore}`);
  return opts;
}

export function query(tasks, opts) {
  const list = (v) => (v ? v.split(',').map((s) => s.trim()).filter(Boolean) : null);
  const statuses = list(opts.status);
  const areas = list(opts.area);
  const owners = list(opts.owner);
  const needle = opts.grep?.toLowerCase();
  const testNeedle = opts.test?.toLowerCase();
  return tasks
    .filter((t) => t.data)
    .filter((t) => (statuses ? statuses.includes(t.data.status) : opts.all || t.data.status !== 'done'))
    .filter((t) => !areas || areas.includes(t.data.area))
    .filter((t) => !owners || owners.includes(t.data.owner))
    .filter((t) => !opts.dueBefore || (t.data.due && t.data.due <= opts.dueBefore))
    .filter((t) => !testNeedle || (t.data.test ?? '').toLowerCase().includes(testNeedle))
    .filter((t) => {
      if (!needle) return true;
      const d = t.data;
      return [d.title, d.brief, d.test, ...(d.refs ?? []), t.body].some((s) => typeof s === 'string' && s.toLowerCase().includes(needle));
    })
    .sort((a, b) => (a.data.due ?? '9999').localeCompare(b.data.due ?? '9999') || a.rel.localeCompare(b.rel));
}

export function formatLine(t) {
  return `${t.rel} — ${t.data.title} — ${t.data.status} — ${t.data.due ?? '-'}`;
}

export function run(argv, out = console.log) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (err) {
    console.error(`todo query: ${err.message}`);
    return 2;
  }
  const hits = query(loadTasks(opts.root), opts);
  if (opts.json) out(JSON.stringify(hits.map((t) => ({ path: t.rel, ...t.data })), null, 2));
  else for (const t of hits) out(formatLine(t));
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exit(run(process.argv.slice(2)));
