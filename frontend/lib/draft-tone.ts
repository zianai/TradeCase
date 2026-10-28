export type DraftTone = "professional" | "concise" | "warm";

const tones = {
  professional: {
    greeting: "Dear",
    generic: "Hello,",
    closing: "Kind regards,",
  },
  concise: { greeting: "Hello", generic: "Hello,", closing: "Regards," },
  warm: { greeting: "Hi", generic: "Hi,", closing: "Warm regards," },
};

// Deliberately local and limited to courtesy lines: no model call, factual
// rewrite, recipient inference, promise, approval, or persistence side effect.
export function applyDraftTone(body: string, tone: DraftTone): string {
  const style = tones[tone];
  const lines = body.split("\n");
  const first = lines.findIndex((line) => line.trim().length > 0);
  const greeting =
    first >= 0
      ? lines[first].trim().match(/^(?:Dear|Hello|Hi)(?: ([^,\r\n]{1,80}))?,$/i)
      : null;
  if (greeting) {
    lines[first] = greeting[1]
      ? `${style.greeting} ${greeting[1]},`
      : style.generic;
  } else {
    lines.unshift(style.generic, "");
  }

  const last = lines.findLastIndex((line) => line.trim().length > 0);
  // Recognize only a complete conventional closing near the end. Everything
  // following it (including the original signature) stays byte-for-byte intact.
  const closing = lines.findLastIndex(
    (line, index) =>
      index > first &&
      index >= last - 5 &&
      /^(?:Best regards|Kind regards|Warm regards|Regards|Sincerely|Best),?$/i.test(
        line.trim(),
      ),
  );
  if (closing >= 0) lines[closing] = style.closing;
  else lines.push("", style.closing);
  return lines.join("\n");
}
