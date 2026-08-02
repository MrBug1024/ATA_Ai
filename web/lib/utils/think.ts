/**
 * Extracts <think>...</think> content from raw LLM output.
 *
 * Handles:
 * - No think tags (returns original as displayText)
 * - Completed think blocks (thinkDone: true)
 * - Unclosed think tags during streaming (thinkDone: false)
 * - Nested think tags (depth tracking)
 * - Think tags surrounded by display text
 */
export function extractThink(raw: string): {
  thinkText: string;
  displayText: string;
  thinkDone: boolean;
} {
  let thinkText = "";
  let displayText = "";
  let depth = 0;
  let hadThink = false;
  let i = 0;

  while (i < raw.length) {
    if (raw.startsWith("<think>", i)) {
      depth++;
      hadThink = true;
      i += 7;
    } else if (raw.startsWith("</think>", i)) {
      if (depth > 0) depth--;
      i += 8;
    } else if (depth > 0) {
      thinkText += raw[i++];
    } else {
      displayText += raw[i++];
    }
  }

  return { thinkText: thinkText.trim(), displayText, thinkDone: hadThink && depth === 0 };
}

/**
 * Removes <think>...</think> content from text and trims whitespace.
 * Convenience wrapper around extractThink for use in display contexts.
 */
export function stripThink(text: string): string {
  return extractThink(text).displayText.trim();
}
