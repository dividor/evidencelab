
import { buildOrderedElements } from '../components/searchResultCardUtils';
import { SearchResult } from '../types/api';

const IMG_15_PATH = '/img15.png';
const IMG_11_PATH = '/img11.png';

describe('Image Filtering Logic', () => {
    const baseResult: SearchResult = {
        chunk_id: '1',
        doc_id: 'doc1',
        text: 'text',
        page_num: 10,
        headings: [],
        score: 1,
        title: 'Title',
        metadata: {}
    };

    describe('Legacy Images (result.images)', () => {
        it('should include images on the same page as text', () => {
            const result: SearchResult = {
                ...baseResult,
                // Simulate legacy structure: explicit ELEMENTS array and IMAGES array
                elements: [
                    { type: 'TextItem', label: 'text', text: 'Text on page 10', page: 10, bbox: [0, 0, 100, 100], position_hint: 0 }
                ],
                // Make image large enough (> 10000 area)
                images: [
                    { path: '/img10.png', page: 10, bbox: [0, 0, 200, 200], position_hint: 1 }
                ]
            };
            const ordered = buildOrderedElements(result);
            expect(ordered.find(el => el.element_type === 'image' && el.path === '/img10.png')).toBeDefined();
        });

        it('should include images on adjacent pages (+/- 1)', () => {
            const result: SearchResult = {
                ...baseResult,
                // Even if text is on page 10, if image says page 11, it is usually filtered by "text overlap" logic
                // UNLESS there is text on page 11 too.
                // The legacy logic dictates: image must overlap with text *on the same page*.
                // So if there is NO text on page 11, the image on page 11 is filtered out by existing logic!
                // So for legacy, "irrelevant" images are ALREADY filtered if there is no text on that page.

                // Let's create a scenario where legacy logic WOULD pass, but my new logic stops it.
                // Text on page 15 (noise), Image on page 15. Result page_num is 10.
                elements: [
                    { type: 'TextItem', label: 'text', text: 'Main text', page: 10, bbox: [0, 0, 100, 100], position_hint: 0 },
                    { type: 'TextItem', label: 'text', text: 'Noise text', page: 15, bbox: [0, 0, 100, 100], position_hint: 0 }
                ],
                // Page 15 is > 10+1. Should be filtered.
                images: [
                    { path: IMG_15_PATH, page: 15, bbox: [0, 0, 200, 200], position_hint: 1 }
                ]
            };

            // New logic: result.page_num is 10. Page 15 is > 10+1. Should be filtered.
            const ordered = buildOrderedElements(result);
            expect(ordered.find(el => el.element_type === 'image' && el.path === IMG_15_PATH)).toBeUndefined();
        });

        it('should allow images within range (e.g. page 11)', () => {
            const result: SearchResult = {
                ...baseResult,
                elements: [
                    { type: 'TextItem', label: 'text', text: 'Main text', page: 10, bbox: [0, 0, 100, 100], position_hint: 0 },
                    { type: 'TextItem', label: 'text', text: 'Next page text', page: 11, bbox: [0, 0, 100, 100], position_hint: 0 }
                ],
                images: [
                    { path: IMG_11_PATH, page: 11, bbox: [0, 0, 200, 200], position_hint: 1 }
                ]
            };

            // Page 11 is within range of 10.
            const ordered = buildOrderedElements(result);
            expect(ordered.find(el => el.element_type === 'image' && el.path === IMG_11_PATH)).toBeDefined();
        });
    });

    describe('Chunk Elements (result.chunk_elements)', () => {
        // Chunk elements logic filters by text overlap AND now by anchor page.

        it('should remove image far from anchor page', () => {
            const result: SearchResult = {
                ...baseResult,
                // Result anchor is 10.
                chunk_elements: [
                    { element_type: 'text', text: 'text p10', page: 10, bbox: [0, 0, 100, 100], position_hint: 0 },
                    // Noise on p15
                    { element_type: 'text', text: 'text p15', page: 15, bbox: [0, 0, 100, 100], position_hint: 0 },
                    // Image on p15 overlapping noise
                    { element_type: 'image', path: IMG_15_PATH, page: 15, bbox: [0, 0, 50, 50], position_hint: 0 }
                ]
            };
            const ordered = buildOrderedElements(result);
            expect(ordered.find(el => el.element_type === 'image' && el.path === IMG_15_PATH)).toBeUndefined();
        });

        it('should keep image near anchor page', () => {
            const result: SearchResult = {
                ...baseResult,
                // Result anchor is 10.
                chunk_elements: [
                    { element_type: 'text', text: 'text p10', page: 10, bbox: [0, 0, 100, 100], position_hint: 0 },
                    { element_type: 'text', text: 'text p11', page: 11, bbox: [0, 0, 100, 100], position_hint: 0 },
                    { element_type: 'image', path: IMG_11_PATH, page: 11, bbox: [0, 0, 200, 200], position_hint: 0 }
                ]
            };
            const ordered = buildOrderedElements(result);
            expect(ordered.find(el => el.element_type === 'image' && el.path === IMG_11_PATH)).toBeDefined();
        });

        it('should remove table far from anchor page', () => {
            const result: SearchResult = {
                ...baseResult,
                // Result anchor is 10.
                chunk_elements: [
                    { element_type: 'text', text: 'text p10', page: 10, bbox: [0, 0, 100, 100], position_hint: 0 },
                    // Table on p25. Previously this would pass because tables were 'true'.
                    { element_type: 'table', image_path: '/table25.png', page: 25, bbox: [0, 0, 50, 50], position_hint: 0 }
                ]
            };
            const ordered = buildOrderedElements(result);
            expect(ordered.find(el => el.element_type === 'table' && el.image_path === '/table25.png')).toBeUndefined();
        });

        it('should INCLUDE far image if referenced in text', () => {
            const result: SearchResult = {
                ...baseResult,
                // Text explicitly references "Figure 2"
                text: "As shown in Figure 2, the data increases.",
                page_num: 14,
                chunk_elements: [
                    { element_type: 'text', text: 'As shown in Figure 2...', page: 14, bbox: [0, 0, 100, 100], position_hint: 0 },
                    // Image technically on page 4 (bad data) but referenced!
                    { element_type: 'image', path: '/fig2.png', page: 4, bbox: [0, 0, 50, 50], position_hint: 0 }
                ]
            };
            const ordered = buildOrderedElements(result);
            // Should be included because of "Figure 2" reference
            expect(ordered.find(el => el.element_type === 'image' && el.path === '/fig2.png')).toBeDefined();
        });

        it('should EXCLUDE far image if NOT referenced in text', () => {
            const result: SearchResult = {
                ...baseResult,
                // Text does NOT reference "Figure 2"
                text: "Some unrelated text.",
                page_num: 14,
                chunk_elements: [
                    { element_type: 'text', text: 'Some unrelated text.', page: 14, bbox: [0, 0, 100, 100], position_hint: 0 },
                    // Image on page 4, unrelated
                    { element_type: 'image', path: '/fig2.png', page: 4, bbox: [0, 0, 50, 50], position_hint: 0 }
                ]
            };
            const ordered = buildOrderedElements(result);
            // Should be excluded (strict filter)
            expect(ordered.find(el => el.element_type === 'image' && el.path === '/fig2.png')).toBeUndefined();
        });
    });
});
