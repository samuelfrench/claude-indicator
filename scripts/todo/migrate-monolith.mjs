#!/usr/bin/env node
// Audit helpers for migrating a monolithic TODO.md to task files under docs/todo/.
// Day-to-day work uses build.mjs and query.mjs; verify checks preservation of original lines.
//
//   node scripts/todo/migrate-monolith.mjs split  <TODO.md> <outDir>
//       Writes <outDir>/S###.md (verbatim section text, heading line included) and
//       <outDir>/sections.json. A section starts at a line beginning with "## ".
//   node scripts/todo/migrate-monolith.mjs apply  <sectionsDir> <metas.json> <repoRoot> <baseRev> <archiveBase.md>
//       Writes docs/todo/<area>/<slug>.md task files (frontmatter + summary + verbatim text),
//       TODO-archive.md = <archiveBase.md> + a [MIGRATED] appendix, and the migration map.
//   node scripts/todo/migrate-monolith.mjs verify <oldTODO.md> <repoRoot> <archiveBase>
//       Proves no line was lost: the multiset of non-empty, whitespace-stripped lines of
//       <oldTODO.md> must be contained in the union of docs/todo/**/*.md plus the lines
//       TODO-archive.md gained relative to <archiveBase> (a copy of the archive before
//       the migration). Exits 1 and prints the missing lines otherwise.
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { expectedRelPath, serializeFrontmatter } from './lib.mjs';

export function splitSections(text) {
  const lines = text.split('\n');
  if (lines.at(-1) === '') lines.pop();
  const sections = [];
  let current = { heading: null, startLine: 1, lines: [] };
  lines.forEach((line, i) => {
    if (line.startsWith('## ')) {
      if (current.lines.length) sections.push(current);
      current = { heading: line, startLine: i + 1, lines: [] };
    }
    current.lines.push(line);
  });
  if (current.lines.length) sections.push(current);
  return sections.map((s, idx) => ({
    idx,
    id: `S${String(idx).padStart(3, '0')}`,
    heading: s.heading,
    startLine: s.startLine,
    lineCount: s.lines.length,
    bytes: Buffer.byteLength(s.lines.join('\n') + '\n'),
    sha1: createHash('sha1').update(s.lines.join('\n')).digest('hex'),
    text: s.lines.join('\n') + '\n',
  }));
}

export function lineMultiset(text) {
  const counts = new Map();
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    counts.set(line, (counts.get(line) ?? 0) + 1);
  }
  return counts;
}

function walkMarkdown(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walkMarkdown(full));
    else if (name.endsWith('.md')) out.push(full);
  }
  return out;
}

export function missingLines(oldText, newTexts) {
  const have = new Map();
  for (const t of newTexts) for (const [line, n] of lineMultiset(t)) have.set(line, (have.get(line) ?? 0) + n);
  const missing = [];
  for (const [line, n] of lineMultiset(oldText)) {
    const got = have.get(line) ?? 0;
    if (got < n) missing.push({ line, need: n, have: got });
  }
  return missing;
}

function archiveGain(archiveText, baseText) {
  // Lines the archive gained: multiset difference archive − base, rendered back as text.
  const base = lineMultiset(baseText);
  const gained = [];
  for (const raw of archiveText.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const n = base.get(line) ?? 0;
    if (n > 0) base.set(line, n - 1);
    else gained.push(line);
  }
  return gained.join('\n');
}

// ---- apply ---------------------------------------------------------------------------------
// metas.json: one entry per section (matched by exact heading), each with
//   disposition: file | merge (mergeIntoHeading) | archive (whole section to TODO-archive.md) | split
//   (the section is replaced by entries carrying `from` + `lines`, 1-based inclusive within it),
//   slug/area/title/status/due/updated/owner/brief/refs/test, summary[] and archiveRanges[[a,b]].
const MIGRATION_DATE = '2026-10-07';
const anchorFor = (slug) => `todo-migration-${MIGRATION_DATE}-${slug}`;

function cutRanges(lines, ranges) {
  // Returns [{ kind: 'keep' | 'cut', lines, from, to }] over 1-based inclusive ranges.
  const sorted = [...ranges].sort((a, b) => a[0] - b[0]);
  const parts = [];
  let next = 1;
  for (const [a, b] of sorted) {
    if (a < next || b < a || b > lines.length) throw new Error(`bad archive range ${a}-${b} (section has ${lines.length} lines)`);
    if (a > next) parts.push({ kind: 'keep', lines: lines.slice(next - 1, a - 1) });
    parts.push({ kind: 'cut', lines: lines.slice(a - 1, b), from: a, to: b });
    next = b + 1;
  }
  if (next <= lines.length) parts.push({ kind: 'keep', lines: lines.slice(next - 1) });
  return parts;
}

export function applyMigration({ sections, metas, baseRev, archiveBase }) {
  const byHeading = new Map();
  for (const m of metas) {
    if (m.from) continue;
    if (byHeading.has(m.heading)) throw new Error(`duplicate meta heading: ${m.heading}`);
    byHeading.set(m.heading, m);
  }
  const missing = sections.filter((s) => !byHeading.has(s.heading));
  if (missing.length) throw new Error(`sections without a meta:\n${missing.map((s) => `  ${s.id} ${s.heading}`).join('\n')}`);
  const secByHeading = new Map(sections.map((s) => [s.heading, s]));
  const files = new Map(); // slug -> { meta, chunks: [{ section, lines, startLine, merged }] }
  const archiveBlocks = [];
  const mapping = [];

  const fileFor = (meta) => {
    if (!files.has(meta.slug)) files.set(meta.slug, { meta, chunks: [] });
    return files.get(meta.slug);
  };
  for (const s of sections) {
    const meta = byHeading.get(s.heading);
    const lines = s.text.replace(/\n$/, '').split('\n');
    if (meta.disposition === 'file') {
      fileFor(meta).chunks.unshift({ section: s, lines, offset: 1, ranges: meta.archiveRanges ?? [], merged: false });
    } else if (meta.disposition === 'merge') {
      const target = byHeading.get(meta.mergeIntoHeading);
      if (!target || target.disposition !== 'file') throw new Error(`${s.id}: merge target missing or not a file: ${meta.mergeIntoHeading}`);
      fileFor(target).chunks.push({ section: s, lines, offset: 1, ranges: meta.archiveRanges ?? [], merged: true });
    } else if (meta.disposition === 'archive') {
      archiveBlocks.push({ title: `Retired TODO.md section: ${(s.heading ?? '(preamble)').replace(/^## /, '')}`, anchor: anchorFor(`section-${s.id.toLowerCase()}`), parts: [{ lines, from: 1, to: lines.length, section: s }] });
      mapping.push({ s, to: 'TODO-archive.md', note: 'retired (not a task) — archived verbatim' });
    } else if (meta.disposition === 'split') {
      const subs = metas.filter((m) => m.from && m.heading === s.heading);
      const covered = new Set();
      for (const sub of subs) {
        for (let i = sub.lines[0]; i <= sub.lines[1]; i++) covered.add(i);
        fileFor(sub).chunks.push({ section: s, lines: lines.slice(sub.lines[0] - 1, sub.lines[1]), offset: sub.lines[0], ranges: sub.archiveRanges ?? [], merged: false });
      }
      const left = lines.map((l, i) => ({ l, n: i + 1 })).filter(({ l, n }) => !covered.has(n) && l.trim() && n !== 1);
      if (left.length) throw new Error(`${s.id}: split leaves lines uncovered: ${left.map((x) => x.n).join(',')}`);
      mapping.push({ s, to: `${subs.length} files`, note: 'split: one known-failure file per entry; heading kept in docs/todo/README.md' });
    } else throw new Error(`${s.id}: unknown disposition ${meta.disposition}`);
  }
  // fileFor(...).chunks.unshift put the owning section first even when a merged section precedes it.

  const out = new Map(); // relPath -> text
  for (const [slug, { meta, chunks }] of files) {
    const rel = expectedRelPath(meta, slug);
    const archiveRel = path.relative(path.dirname(rel), 'TODO-archive.md');
    const anchor = anchorFor(slug);
    const refs = [...(meta.refs ?? [])];
    const body = [];
    const summary = meta.summary.map((l) => `- ${l.replace(/^-\s+/, '')}`);
    body.push(...summary, '');
    const archived = [];
    for (const c of chunks) {
      const first = c.section.startLine + c.offset - 1;
      const last = first + c.lines.length - 1;
      const verb = c.merged ? 'Merged (duplicate/superseded section)' : 'Migrated';
      body.push(`<!-- ${verb} verbatim from TODO.md @ ${baseRev}, lines ${first}-${last}, on ${MIGRATION_DATE}. -->`);
      for (const part of cutRanges(c.lines, c.ranges)) {
        if (part.kind === 'keep') body.push(...part.lines);
        else {
          const a = first + part.from - 1;
          const b = first + part.to - 1;
          body.push(`> Older history (TODO.md lines ${a}-${b}) moved verbatim to [TODO-archive.md](${archiveRel}#${anchor}) on ${MIGRATION_DATE}.`);
          archived.push({ lines: part.lines, from: a, to: b, section: c.section });
        }
      }
      body.push('');
      mapping.push({ s: c.section, lines: [first, last], to: rel, note: [c.merged && 'merged', c.ranges.length && 'history archived'].filter(Boolean).join(', ') });
    }
    if (archived.length) {
      archiveBlocks.push({ title: `${meta.title} — history moved out of \`${rel}\``, anchor, parts: archived });
      const ref = `TODO-archive.md#${anchor}`;
      if (!refs.includes(ref)) refs.push(ref);
    }
    const data = { ...meta, refs, test: meta.test ?? null, due: meta.due ?? null };
    out.set(rel, serializeFrontmatter(data) + '\n' + body.join('\n').replace(/\n+$/, '') + '\n');
  }

  let archive = archiveBase.replace(/\n*$/, '\n');
  if (archiveBlocks.length) {
    archive += `\n## [MIGRATED ${MIGRATION_DATE}] History moved out of TODO.md by the task-file restructure\n\n`;
    archive += `TODO.md became a generated index of \`docs/todo/<area>/<slug>.md\` task files on ${MIGRATION_DATE} (source TODO.md @ ${baseRev}). Long histories that would have pushed a task file past ~150 lines, and retired non-task sections, moved here verbatim. Each block links back to its task file.\n`;
    for (const block of archiveBlocks) {
      archive += `\n<a id="${block.anchor}"></a>\n### ${block.title}\n`;
      for (const p of block.parts) archive += `\n<!-- TODO.md @ ${baseRev}, lines ${p.section.startLine + p.from - 1}-${p.section.startLine + p.to - 1} -->\n${p.lines.join('\n')}\n`;
    }
  }

  const esc = (t) => t.replace(/\|/g, '\\|');
  const rows = mapping
    .sort((a, b) => a.s.startLine - b.s.startLine || (a.lines?.[0] ?? 0) - (b.lines?.[0] ?? 0))
    .map((m) => {
      const lines = m.lines ? `${m.lines[0]}-${m.lines[1]}` : `${m.s.startLine}-${m.s.startLine + m.s.lineCount - 1}`;
      const heading = esc((m.s.heading ?? '(preamble)').replace(/^## /, '').slice(0, 110));
      const to = m.to.endsWith('.md') && m.to.startsWith('docs/todo/') ? `[${m.to.replace('docs/todo/', '')}](${m.to.replace('docs/todo/', '')})` : m.to;
      return `| ${m.s.id} | ${lines} | ${heading} | ${to} | ${m.note || ''} |`;
    });
  const mappingDoc = [
    `# TODO.md → task files: migration map (${MIGRATION_DATE})`,
    '',
    `Source: \`TODO.md\` @ \`${baseRev}\` (${sections.length} \`## \` sections). Produced by \`node scripts/todo/migrate-monolith.mjs\`. Every non-empty line of the old file is in a task file below or in the \`[MIGRATED ${MIGRATION_DATE}]\` appendix of \`TODO-archive.md\` (proof: \`migrate-monolith.mjs verify\`). Merged sections were duplicates or superseded versions of the same task.`,
    '',
    '| Section | Old lines | Old heading (first 110 chars) | New file | Note |',
    '|---|---|---|---|---|',
    ...rows,
    '',
  ].join('\n');
  return { files: out, archive, mappingDoc };
}

const [cmd, ...args] = process.argv.slice(2);
if (cmd === 'apply') {
  // apply <sectionsDir> <metas.json> <repoRoot> <baseRev> <archiveBase.md>
  const [sectionsDir, metasPath, repoRoot, baseRev, archiveBasePath] = args;
  const index = JSON.parse(readFileSync(path.join(sectionsDir, 'sections.json'), 'utf8'));
  const sections = index.map((s) => ({ ...s, text: readFileSync(path.join(sectionsDir, `${s.id}.md`), 'utf8') }));
  const metas = JSON.parse(readFileSync(metasPath, 'utf8'));
  const { files, archive, mappingDoc } = applyMigration({ sections, metas, baseRev, archiveBase: readFileSync(archiveBasePath, 'utf8') });
  const todoDir = path.join(repoRoot, 'docs/todo');
  mkdirSync(todoDir, { recursive: true });
  for (const name of readdirSync(todoDir)) {
    const full = path.join(todoDir, name);
    if (statSync(full).isDirectory()) rmSync(full, { recursive: true }); // task dirs are regenerated wholesale
  }
  for (const [rel, text] of files) {
    mkdirSync(path.dirname(path.join(repoRoot, rel)), { recursive: true });
    writeFileSync(path.join(repoRoot, rel), text);
  }
  writeFileSync(path.join(repoRoot, 'TODO-archive.md'), archive);
  writeFileSync(path.join(todoDir, `migration-${MIGRATION_DATE}.md`), mappingDoc);
  console.log(`wrote ${files.size} task files, TODO-archive.md appendix and docs/todo/migration-${MIGRATION_DATE}.md`);
} else if (cmd === 'split') {
  const [todoPath, outDir] = args;
  mkdirSync(outDir, { recursive: true });
  const sections = splitSections(readFileSync(todoPath, 'utf8'));
  for (const s of sections) writeFileSync(path.join(outDir, `${s.id}.md`), s.text);
  writeFileSync(
    path.join(outDir, 'sections.json'),
    JSON.stringify(sections.map(({ text, ...rest }) => rest), null, 2) + '\n',
  );
  console.log(`split ${sections.length} sections into ${outDir}`);
} else if (cmd === 'verify') {
  const [oldPath, repoRoot, archiveBasePath] = args;
  const oldText = readFileSync(oldPath, 'utf8');
  const files = walkMarkdown(path.join(repoRoot, 'docs/todo'));
  const texts = files.map((f) => readFileSync(f, 'utf8'));
  texts.push(archiveGain(readFileSync(path.join(repoRoot, 'TODO-archive.md'), 'utf8'), readFileSync(archiveBasePath, 'utf8')));
  const missing = missingLines(oldText, texts);
  const old = lineMultiset(oldText);
  const total = [...old.values()].reduce((a, b) => a + b, 0);
  console.log(`old non-empty lines: ${total} (${old.size} distinct); docs/todo files: ${files.length}; missing: ${missing.length}`);
  for (const m of missing.slice(0, 50)) console.log(`MISSING x${m.need - m.have}: ${m.line.slice(0, 200)}`);
  process.exit(missing.length ? 1 : 0);
} else if (cmd) {
  console.error(`unknown command ${cmd}`);
  process.exit(2);
}
