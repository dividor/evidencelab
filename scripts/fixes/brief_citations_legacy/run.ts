// Render every brief of a `briefs` dump the way the browser did before
// citation handling moved into the API, for the conversion dry run to compare
// against. Usage (from ui/frontend, which has the TypeScript compiler):
//   npx tsc --outDir /tmp/legacy --module commonjs --target es2019 \
//     ../../scripts/fixes/brief_citations_legacy/*.ts
//   node /tmp/legacy/run.js <dump.json> <legacy.json>
// The dump is the JSON array `scripts/fixes/convert_brief_citations.py --dump`
// writes: [{id, title, content}] with content in the legacy shape.
import * as fs from 'fs';
import { BriefSection, buildGlobalCitations } from './buildGlobalCitations.legacy';

const [dumpPath, outPath] = process.argv.slice(2);
if (!dumpPath || !outPath) {
  throw new Error('usage: node run.js <dump.json> <legacy.json>');
}
const rows = JSON.parse(fs.readFileSync(dumpPath, 'utf8')) as Array<{
  id: string;
  content: { sections?: Array<Record<string, unknown>> };
}>;
const out: Record<string, unknown> = {};
for (const row of rows) {
  const sections: BriefSection[] = (row.content.sections || []).map((s, i) => ({
    id: (s.id as string) || `sec${i + 1}`,
    title: (s.title as string) || '',
    status: (s.status as string) || 'pending',
    content: (s.content as string) || '',
    sources: (s.sources as BriefSection['sources']) || [],
  }));
  const { refs, display } = buildGlobalCitations(sections, 'passage');
  const displayOut: Record<string, unknown> = {};
  display.forEach((d, id) => {
    displayOut[id] = {
      content: d.content,
      sources: d.sources.map((s) => ({ index: s.index, chunkId: s.chunkId, page: s.page ?? null })),
    };
  });
  out[row.id] = {
    sections: displayOut,
    refs: refs.map((r) => ({ n: r.n, chunkId: r.source.chunkId, page: r.page ?? null })),
  };
}
fs.writeFileSync(outPath, JSON.stringify(out, null, 1));
console.log(`wrote ${Object.keys(out).length} briefs to ${outPath}`);
