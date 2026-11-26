/** A written reason that says something, the same rule the API enforces (booklantern.posting.real_reason): at least 12 characters, at least 2 words and at least 5 different letters or digits. */
export const REASON_HELP = "Write a real reason: at least 12 characters in at least 2 words, saying what you checked.";

export function realReason(note: string): boolean {
  const text = note.trim().replace(/\s+/g, " ");
  const distinct = new Set([...text.toLowerCase()].filter((c) => /[\p{L}\p{N}]/u.test(c)));
  return text.length >= 12 && text.split(" ").length >= 2 && distinct.size >= 5;
}
