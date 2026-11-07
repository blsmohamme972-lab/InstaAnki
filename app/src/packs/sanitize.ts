import createDOMPurify from 'dompurify';

export type SvgSanitizer = (svg: string) => string;

/**
 * Defense in depth: the validator already rejects scripts, handlers and external links, and the
 * SVG is then re-serialized through DOMPurify's SVG profile before it is stored or inlined.
 */
export function createSvgSanitizer(win: Window): SvgSanitizer {
  const purify = createDOMPurify(win as Window & typeof globalThis);
  return (svg) => {
    const clean = purify.sanitize(svg, {
      USE_PROFILES: { svg: true, svgFilters: true },
      FORBID_TAGS: ['foreignObject', 'script', 'style'],
    });
    const rootTag = /<svg\b[^>]*>/i.exec(clean);
    if (!rootTag) throw new Error('SVG sanitization produced an empty document');
    // keep the file usable as a standalone image (<img src>) as well as inline
    if (!/\sxmlns\s*=/.test(rootTag[0])) {
      return clean.replace(/<svg\b/i, '<svg xmlns="http://www.w3.org/2000/svg"');
    }
    return clean;
  };
}
