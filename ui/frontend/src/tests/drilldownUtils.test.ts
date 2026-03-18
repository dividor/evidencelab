import { DrilldownNode } from '../types/api';
import {
  serializeDrilldownTree,
  serializeFullDrilldownTree,
  patchNodeInTree,
} from '../utils/drilldownUtils';

const makeSampleTree = (): DrilldownNode => ({
  id: 'root',
  label: 'Climate adaptation',
  summary: 'Root summary about climate',
  prompt: 'Summarize climate adaptation',
  results: [{
    chunk_id: 'r1', doc_id: 'd1', text: 'result text', title: 'Doc 1', score: 0.9,
    headings: ['H1'], page_num: 1, organization: 'UN', year: '2024',
    metadata: { heavy_field: 'x'.repeat(1000) },
  } as any],
  translatedText: null,
  translatedLang: null,
  expanded: false,
  children: [
    {
      id: 'dd-1',
      label: 'Resilience',
      summary: 'Child summary about resilience',
      prompt: 'Summarize resilience',
      results: [],
      translatedText: 'Resumen traducido',
      translatedLang: 'es',
      expanded: true,
      children: [
        {
          id: 'dd-2',
          label: 'Urban resilience',
          summary: 'Grandchild summary',
          prompt: 'Summarize urban resilience',
          results: [],
          translatedText: null,
          translatedLang: null,
          expanded: false,
          children: [],
        },
      ],
    },
    {
      id: 'dd-3',
      label: 'Food security',
      summary: 'Food security summary',
      prompt: 'Summarize food security',
      results: [],
      translatedText: null,
      translatedLang: null,
      expanded: false,
      children: [],
    },
  ],
});

describe('serializeDrilldownTree (lightweight)', () => {
  test('preserves only id, label, and children structure', () => {
    const tree = makeSampleTree();
    const serialized = serializeDrilldownTree(tree);

    expect(serialized.id).toBe('root');
    expect(serialized.label).toBe('Climate adaptation');
    expect(serialized.children).toHaveLength(2);
    expect(serialized).not.toHaveProperty('summary');
    expect(serialized).not.toHaveProperty('prompt');
    expect(serialized).not.toHaveProperty('results');
  });

  test('recurses into children', () => {
    const tree = makeSampleTree();
    const serialized = serializeDrilldownTree(tree);

    expect(serialized.children[0].id).toBe('dd-1');
    expect(serialized.children[0].label).toBe('Resilience');
    expect(serialized.children[0]).not.toHaveProperty('summary');
    expect(serialized.children[0].children).toHaveLength(1);
    expect(serialized.children[0].children[0].id).toBe('dd-2');
  });
});

describe('serializeFullDrilldownTree', () => {
  test('preserves summary, translations, and slim results but strips prompt', () => {
    const tree = makeSampleTree();
    const serialized = serializeFullDrilldownTree(tree);

    expect(serialized.id).toBe('root');
    expect(serialized.summary).toBe('Root summary about climate');
    // Prompt is stripped to empty string to save space
    expect(serialized.prompt).toBe('');
    expect(serialized.results).toHaveLength(1);
    expect(serialized.expanded).toBe(false);
    expect(serialized.translatedText).toBeNull();
    expect(serialized.translatedLang).toBeNull();
  });

  test('strips heavy metadata from results, keeps display fields', () => {
    const tree = makeSampleTree();
    const serialized = serializeFullDrilldownTree(tree);
    const result = serialized.results[0];

    // Display fields preserved
    expect(result.chunk_id).toBe('r1');
    expect(result.doc_id).toBe('d1');
    expect(result.text).toBe('result text');
    expect(result.title).toBe('Doc 1');
    expect(result.score).toBe(0.9);
    expect(result.headings).toEqual(['H1']);
    expect(result.organization).toBe('UN');
    expect(result.year).toBe('2024');
    // Heavy metadata is stripped
    expect(result.metadata).toBeUndefined();
    expect(result.chunk_elements).toBeUndefined();
    expect(result.tables).toBeUndefined();
    expect(result.images).toBeUndefined();
  });

  test('preserves translation data on children', () => {
    const tree = makeSampleTree();
    const serialized = serializeFullDrilldownTree(tree);
    const child = serialized.children[0];

    expect(child.translatedText).toBe('Resumen traducido');
    expect(child.translatedLang).toBe('es');
    expect(child.expanded).toBe(true);
  });

  test('recurses fully into nested children', () => {
    const tree = makeSampleTree();
    const serialized = serializeFullDrilldownTree(tree);
    const grandchild = serialized.children[0].children[0];

    expect(grandchild.id).toBe('dd-2');
    expect(grandchild.summary).toBe('Grandchild summary');
    expect(grandchild.children).toHaveLength(0);
  });
});

describe('patchNodeInTree', () => {
  test('patches root node summary and results', () => {
    const tree = makeSampleTree();
    const newResults = [{ chunk_id: 'new1' } as any];
    const patched = patchNodeInTree(tree, 'root', 'Updated root summary', newResults);

    expect(patched.summary).toBe('Updated root summary');
    expect(patched.results).toEqual(newResults);
    // Original tree is not mutated
    expect(tree.summary).toBe('Root summary about climate');
  });

  test('patches a child node', () => {
    const tree = makeSampleTree();
    const patched = patchNodeInTree(tree, 'dd-1', 'Updated child', []);

    expect(patched.children[0].summary).toBe('Updated child');
    // Root is unchanged
    expect(patched.summary).toBe('Root summary about climate');
    // Sibling is unchanged
    expect(patched.children[1].summary).toBe('Food security summary');
  });

  test('patches a deeply nested node', () => {
    const tree = makeSampleTree();
    const patched = patchNodeInTree(tree, 'dd-2', 'Updated grandchild', []);
    const grandchild = patched.children[0].children[0];

    expect(grandchild.summary).toBe('Updated grandchild');
    expect(grandchild.results).toEqual([]);
  });

  test('returns unchanged tree when target ID not found', () => {
    const tree = makeSampleTree();
    const patched = patchNodeInTree(tree, 'nonexistent', 'No effect', []);

    expect(patched.summary).toBe('Root summary about climate');
    expect(patched.children[0].summary).toBe('Child summary about resilience');
  });
});
