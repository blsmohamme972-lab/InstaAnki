import { describe, expect, it } from 'vitest';
import { fromBase64, toBase64 } from './base64';

describe('base64', () => {
  it('round-trips binary data larger than one chunk', () => {
    const data = new Uint8Array(100_000).map((_, i) => (i * 31) % 256);
    expect(fromBase64(toBase64(data))).toEqual(data);
    expect(toBase64(new Uint8Array([0, 255, 128]))).toBe(Buffer.from([0, 255, 128]).toString('base64'));
  });
});
