/**
 * Normalize spoken number forms into digits for the voice input adapter.
 *
 * Browser speech recognition frequently returns phone numbers as spoken digit
 * words ("zero eight zero three") instead of digits, and may separate digit
 * groups with spaces or hyphens. The deterministic backend parser already
 * strips separators from a numeric run, but it never converts words to digits
 * (see `agent/request_understanding.py`). This module performs that conversion
 * for voice input only, before the transcript is placed in the request field.
 *
 * Two kinds of runs are understood:
 *
 * 1. Digit runs (phone numbers): sequences of digit words (`zero`..`nine`),
 *    pure numeric tokens, and the multipliers `double`/`triple`. Runs that
 *    already consist only of numeric tokens are returned unchanged so a spoken
 *    "0803 000 0001" keeps its grouping verbatim.
 * 2. Amount runs: sequences that include tens/scale words (`thousand`,
 *    `hundred`, `million`, ...) are converted to their numeric value.
 *
 * Ordinary words are never rewritten: a lone "one" or "four" in a sentence is
 * left alone because it is not part of a digit run long enough to be a phone
 * number, and a run without numeric words is never touched. This function only
 * formats recognized input; it makes no policy, routing, or outcome decisions.
 */

const DIGIT_WORDS: Readonly<Record<string, string>> = {
  zero: '0',
  oh: '0',
  nought: '0',
  naught: '0',
  one: '1',
  two: '2',
  three: '3',
  four: '4',
  five: '5',
  six: '6',
  seven: '7',
  eight: '8',
  nine: '9',
}

const MULTIPLIER_WORDS: Readonly<Record<string, number>> = {
  double: 2,
  triple: 3,
}

const SMALL_WORDS: Readonly<Record<string, number>> = {
  ten: 10,
  eleven: 11,
  twelve: 12,
  thirteen: 13,
  fourteen: 14,
  fifteen: 15,
  sixteen: 16,
  seventeen: 17,
  eighteen: 18,
  nineteen: 19,
  twenty: 20,
  thirty: 30,
  forty: 40,
  fifty: 50,
  sixty: 60,
  seventy: 70,
  eighty: 80,
  ninety: 90,
}

const SCALE_WORDS: Readonly<Record<string, number>> = {
  hundred: 100,
  thousand: 1000,
  million: 1_000_000,
  billion: 1_000_000_000,
}

// Minimum number of digits for a run to be treated as a phone number. This is
// what keeps a stray spoken "one" or an amount like "five" from being rewritten.
const MIN_PHONE_DIGITS = 7

const TOKEN_RE = /[A-Za-z]+|\d+|[^A-Za-z\d]+/g
const SEPARATOR_RE = /^[\s,.-]+$/
const NUMERIC_TOKEN_RE = /^\d+$/

function isNumberWord(token: string): boolean {
  const lower = token.toLowerCase()
  return (
    lower in DIGIT_WORDS ||
    lower in MULTIPLIER_WORDS ||
    lower in SMALL_WORDS ||
    lower in SCALE_WORDS
  )
}

function isNumericToken(token: string): boolean {
  return NUMERIC_TOKEN_RE.test(token) || isNumberWord(token)
}

function isAndWord(token: string): boolean {
  return token.toLowerCase() === 'and'
}

function expandDigitRun(tokens: string[]): string | null {
  let digits = ''
  let pendingMultiplier = 1
  for (const token of tokens) {
    const lower = token.toLowerCase()
    if (lower in MULTIPLIER_WORDS) {
      pendingMultiplier = MULTIPLIER_WORDS[lower]
      continue
    }
    const digit = NUMERIC_TOKEN_RE.test(token) ? token : DIGIT_WORDS[lower]
    if (digit === undefined) {
      return null
    }
    digits += digit.repeat(pendingMultiplier)
    pendingMultiplier = 1
  }
  return digits.length >= MIN_PHONE_DIGITS ? digits : null
}

function parseValueRun(tokens: string[]): string | null {
  let total = 0
  let current = 0
  let sawValue = false
  for (const token of tokens) {
    const lower = token.toLowerCase()
    if (NUMERIC_TOKEN_RE.test(token)) {
      current += Number(token)
      sawValue = true
    } else if (lower in DIGIT_WORDS) {
      current += Number(DIGIT_WORDS[lower])
      sawValue = true
    } else if (lower in SMALL_WORDS) {
      current += SMALL_WORDS[lower]
      sawValue = true
    } else if (lower in SCALE_WORDS) {
      const scale = SCALE_WORDS[lower]
      if (scale === 100) {
        current = (current || 1) * scale
      } else {
        total += (current || 1) * scale
        current = 0
      }
      sawValue = true
    } else {
      return null
    }
  }
  const value = total + current
  return sawValue && value > 0 ? String(value) : null
}

function convertRun(tokens: string[]): string | null {
  const hasNumericWord = tokens.some((token) => !NUMERIC_TOKEN_RE.test(token))
  if (!hasNumericWord) {
    // A run of pure digits (for example "0803 000 0001") is preserved verbatim.
    return null
  }
  const usesScale = tokens.some(
    (token) => token.toLowerCase() in SMALL_WORDS || token.toLowerCase() in SCALE_WORDS,
  )
  return usesScale ? parseValueRun(tokens) : expandDigitRun(tokens)
}

/**
 * Rewrite spoken number forms in `text` into digits, leaving all other words
 * untouched. Safe to call repeatedly: an already-normalized transcript is
 * returned unchanged.
 */
export function normalizeSpokenText(text: string): string {
  const tokens = text.match(TOKEN_RE)
  if (!tokens) {
    return text
  }

  let output = ''
  let index = 0
  while (index < tokens.length) {
    const token = tokens[index]
    if (!isNumericToken(token)) {
      output += token
      index += 1
      continue
    }

    const runTokens: string[] = [token]
    let runEnd = index
    let cursor = index + 1
    while (cursor < tokens.length && SEPARATOR_RE.test(tokens[cursor])) {
      let next = cursor + 1
      if (next < tokens.length && isAndWord(tokens[next])) {
        next += 1
      }
      if (next < tokens.length && isNumericToken(tokens[next])) {
        runTokens.push(tokens[next])
        runEnd = next
        cursor = next + 1
      } else {
        break
      }
    }

    const runText = tokens.slice(index, runEnd + 1).join('')
    output += convertRun(runTokens) ?? runText
    index = runEnd + 1
  }
  return output
}

/**
 * Return the most likely phone number in `text` (10-14 digits), or null.
 *
 * Used only for visible feedback in the voice UI. It is deliberately
 * conservative: only long digit runs are surfaced, so an amount such as
 * "5000" is never mistaken for a phone number. The value is derived from the
 * transcript, never invented, and is not authoritative.
 */
export function findPhoneNumber(text: string): string | null {
  const normalized = normalizeSpokenText(text)
  const candidates = normalized.match(/\d[\d \t-]*\d/g) ?? []
  let best: string | null = null
  for (const candidate of candidates) {
    const digits = candidate.replace(/\D/g, '')
    if (digits.length >= 10 && digits.length <= 14) {
      if (best === null || digits.length > best.length) {
        best = digits
      }
    }
  }
  return best
}
