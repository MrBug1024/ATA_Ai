export interface SlashParse {
  /** The word after the leading `/`, e.g. `"case"` for `/case 张三`. */
  command: string;
  /** Trimmed argument substring after the first space on the command line. */
  arg: string;
  /** Index where the command line ends (exclusive of trailing `\n`). */
  lineEnd: number;
}

/**
 * Parse the leading slash command on the first line of composer text.
 * Returns the parsed command word + argument, or `null` when the text does
 * not start with `/`. The slash command is constrained to the first line —
 * anything after the first newline is preserved as normal message body.
 */
export function parseSlash(value: string): SlashParse | null {
  if (!value.startsWith("/")) return null;
  const newlineIdx = value.indexOf("\n");
  const lineEnd = newlineIdx === -1 ? value.length : newlineIdx;
  const line = value.slice(1, lineEnd);
  const spaceIdx = line.indexOf(" ");
  const command = spaceIdx === -1 ? line : line.slice(0, spaceIdx);
  const arg = spaceIdx === -1 ? "" : line.slice(spaceIdx + 1).trim();
  return { command, arg, lineEnd };
}

/** Strip the slash-command line from `value`, including its trailing `\n`. */
export function stripSlashLine(value: string): string {
  const m = parseSlash(value);
  if (!m) return value;
  return value.slice(m.lineEnd).replace(/^\n/, "");
}

export interface SlashCommandDef {
  /** Identifier — matched against `parseSlash().command`. */
  key: string;
  /** Display label, including the leading `/`. */
  label: string;
  /** Short description shown in the command palette. */
  description: string;
}

/**
 * Filter slash-command definitions whose key starts with `prefix`.
 * Used to render the stage-1 command palette as the user types `/c`, `/ca`, …
 */
export function filterCommands(
  commands: readonly SlashCommandDef[],
  prefix: string
): SlashCommandDef[] {
  if (prefix === "") return [...commands];
  const p = prefix.toLowerCase();
  return commands.filter((c) => c.key.toLowerCase().startsWith(p));
}
