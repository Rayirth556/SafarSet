import { describe, expect, it } from 'vitest'

// WCAG contrast of the design tokens (see src/index.css). Text >= 4.5:1; status bars and graphical marks >= 3:1.
const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const ratio = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const card = '#ffffff', page = '#f3f5f9', navy = '#1f3a6e', saffron = '#f39a2e', ink = '#1b2333', ink2 = '#586274'
const text: [string, string, string][] = [
  ['ink on card', ink, card], ['ink on page', ink, page], ['secondary on card', ink2, card], ['secondary on page', ink2, page],
  ['white on navy', '#ffffff', navy], ['ink on saffron (Approve)', ink, saffron],
  ['confirmed text', '#1e7d4f', card], ['tentative text', '#a15c00', card], ['unresolved text', '#b3261e', card], ['boarded text', '#1f5fae', card],
]
const marks: [string, string][] = [
  ['confirmed bar', '#2e9e64'], ['tentative bar', '#c27803'], ['unresolved bar', '#c62828'], ['boarded bar', '#1f5fae'],
]

describe('design token contrast', () => {
  for (const [name, fg, bg] of text) it(`${name} >= 4.5:1`, () => expect(ratio(fg, bg)).toBeGreaterThanOrEqual(4.5))
  for (const [name, c] of marks) it(`${name} >= 3:1 on card`, () => expect(ratio(c, card)).toBeGreaterThanOrEqual(3))
})
