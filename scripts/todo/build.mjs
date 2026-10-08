#!/usr/bin/env node
// Generates TODO.md and docs/todo/index.json from the task files under docs/todo/.
//
//   node scripts/todo/build.mjs                 move misfiled task files, then regenerate both outputs
//   node scripts/todo/build.mjs --archive-done  only move files (done -> docs/todo/done/<area>/, reopened
//                                               or re-areaed files back to docs/todo/<area>/)
//   node scripts/todo/build.mjs --check         write nothing; exit 1 when a task file is invalid or
//                                               misfiled, or TODO.md / index.json are stale
//   --root <dir>                                operate on another checkout (tests use a temp dir)
//
// Output depends only on the task files (no clock, no git), so --check is stable across days and
// machines. Rules for the task files themselves: docs/todo/README.md.
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { REPO_ROOT, expectedRelPath, loadTasks, renderIndex, renderTodo } from './lib.mjs';

export function plan(root) {
  const tasks = loadTasks(root);
  const problems = [];
  const moves = [];
  const seen = new Map();
  for (const task of tasks) {
    for (const err of task.errors) problems.push(`${task.rel}: ${err}`);
    const prior = seen.get(task.slug);
    if (prior) problems.push(`${task.rel}: slug "${task.slug}" is also used by ${prior}`);
    seen.set(task.slug, task.rel);
    if (task.errors.length) continue;
    const want = expectedRelPath(task.data, task.slug);
    if (want !== task.rel) moves.push({ task, from: task.rel, to: want });
  }
  return { tasks, problems, moves };
}

function applyMoves(root, moves) {
  for (const { task, from, to } of moves) {
    const dest = path.join(root, to);
    if (existsSync(dest)) throw new Error(`cannot move ${from}: ${to} already exists`);
    mkdirSync(path.dirname(dest), { recursive: true });
    renameSync(path.join(root, from), dest);
    task.rel = to;
    task.full = dest;
    console.log(`moved ${from} -> ${to}`);
  }
}

export function run(argv) {
  let root = REPO_ROOT;
  const flags = new Set();
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--root') root = path.resolve(argv[++i]);
    else if (['--check', '--archive-done'].includes(argv[i])) flags.add(argv[i]);
    else {
      console.error(`unknown argument ${argv[i]}`);
      return 2;
    }
  }
  const { tasks, problems, moves } = plan(root);
  const todoPath = path.join(root, 'TODO.md');
  const indexPath = path.join(root, 'docs/todo/index.json');

  if (flags.has('--check')) {
    for (const { from, to } of moves) problems.push(`${from}: misfiled — status/area say it belongs at ${to} (run node scripts/todo/build.mjs)`);
    if (!problems.length) {
      const read = (p) => (existsSync(p) ? readFileSync(p, 'utf8') : null);
      if (read(todoPath) !== renderTodo(tasks)) problems.push('TODO.md is stale or hand-edited — run node scripts/todo/build.mjs and commit the result');
      if (read(indexPath) !== renderIndex(tasks)) problems.push('docs/todo/index.json is stale — run node scripts/todo/build.mjs and commit the result');
    }
    for (const p of problems) console.error(`todo check: ${p}`);
    if (problems.length) return 1;
    console.log(`todo check: ok (${tasks.length} task files)`);
    return 0;
  }

  if (problems.length) {
    for (const p of problems) console.error(`todo build: ${p}`);
    console.error('todo build: fix the task files above; nothing was written');
    return 1;
  }
  applyMoves(root, moves);
  if (flags.has('--archive-done')) return 0;
  writeFileSync(todoPath, renderTodo(tasks));
  mkdirSync(path.dirname(indexPath), { recursive: true });
  writeFileSync(indexPath, renderIndex(tasks));
  const open = tasks.filter((t) => t.data.status !== 'done').length;
  console.log(`todo build: wrote TODO.md (${open} open) and docs/todo/index.json (${tasks.length} tasks)`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exit(run(process.argv.slice(2)));
