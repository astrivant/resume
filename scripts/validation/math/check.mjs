import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import katex from 'katex';
import remarkMath from 'remark-math';
import remarkParse from 'remark-parse';
import { unified } from 'unified';

const parser = unified().use(remarkParse).use(remarkMath);
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');

// Parse Markdown structurally so examples inside ordinary code fences and inline code are never interpreted as math.
export function validate(source, filename) {
  const errors = [];
  let count = 0;

  function visit(node) {
    const fenced = node.type === 'code' && node.lang === 'math';
    const display = fenced || node.type === 'math';

    if (display || node.type === 'inlineMath') {
      count += 1;
      const location = `${filename}:${node.position.start.line}:${node.position.start.column}`;
      const raw = source.slice(node.position.start.offset, node.position.end.offset).trimEnd();

      // Markdown tolerates unclosed blocks; published equations must have explicit closing delimiters.
      if (display) {
        const lines = raw.split(/\r?\n/);
        const opening = lines[0].match(/^\s*(`{3,}|~{3,}|\${2,})/);
        const marker = opening?.[1];
        const closing = lines.at(-1).trim();
        if (!marker || lines.length < 2 || closing.length < marker.length || [...closing].some(char => char !== marker[0])) {
          errors.push(`${location}: unclosed math block`);
          return;
        }
      }

      try {
        katex.renderToString(node.value, {
          displayMode: display,
          throwOnError: true,
          strict: 'error',
          trust: false,
          macros: {},
          maxExpand: 1000,
        });
      } catch (error) {
        errors.push(`${location}: ${error.message}`);
      }
    }

    for (const child of node.children ?? []) {
      visit(child);
    }
  }

  visit(parser.parse(source));
  return { count, errors };
}

export function main(paths) {
  // Include new, untracked docs in local checks, while respecting ignored artifacts and dependency directories.
  if (paths.length === 0) {
    paths = execFileSync('git', ['-C', root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '*.md', '*.markdown'], {
      encoding: 'utf8',
    }).split('\0').filter(Boolean).map(path => resolve(root, path));
  }

  let count = 0;
  let failures = 0;

  for (const path of new Set(paths.filter(existsSync))) {
    const result = validate(readFileSync(path, 'utf8'), relative(root, path));
    count += result.count;
    failures += result.errors.length;

    for (const error of result.errors) {
      console.error(error);
    }
  }

  console.log(`Math syntax: ${count} expressions checked, ${failures} errors.`);
  return failures ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  process.exitCode = main(process.argv.slice(2));
}
