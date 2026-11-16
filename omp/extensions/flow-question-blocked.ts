// Shows a herdr-app tab as blocked ("needs you") while an agent waits for the answer to a
// question it wrote in the chat instead of asking it with the `ask` tool.
// A turn that ends with a `### Q<n> · <decision>` heading (the Flow Analyst's question
// format) reports `blocked` over OSC 7501, the program-status sequence omp itself sends
// (packages/coding-agent/src/utils/run-status.ts). omp reports `done` at the end of the
// turn and only reports again when its own state changes, so `blocked` holds until the
// answer starts the next turn and omp reports `working`.

const QUESTION_HEADING = /^#{1,6}\s*Q\d+\s*·\s*(.+)$/m;
const QUESTION_LINE = /^\*\*Question:\*\*\s*(.+)$/m;
// omp writes its own end-of-turn status right after `agent_end`; report after it.
const REPORT_DELAY_MS = 300;
const MAX_MESSAGE = 2048;

type ContentPart = { type: string; text?: string };
type AgentMessage = { role: string; content?: string | ContentPart[] };
type AgentEndEvent = { messages?: AgentMessage[]; willContinue?: boolean };

interface ExtensionApi {
  on(event: "agent_end", handler: (event: AgentEndEvent) => void): void;
  on(event: "agent_start", handler: () => void): void;
}

function lastAssistantText(messages: AgentMessage[]): string {
  const assistant = messages.findLast((message) => message.role === "assistant");
  if (!assistant || !Array.isArray(assistant.content)) {
    return typeof assistant?.content === "string" ? assistant.content : "";
  }
  return assistant.content
    .flatMap((part) => (part.type === "text" && typeof part.text === "string" ? [part.text] : []))
    .join("\n");
}

function reportBlocked(question: string) {
  if (!process.stdout.isTTY) {
    return;
  }
  const message = Buffer.from(question.replace(/\s+/g, " ").trim().slice(0, MAX_MESSAGE)).toString("base64");
  process.stdout.write(`\x1b]7501;state=blocked:kind=question:app=omp:msg=${message}\x1b\\`);
}

export default function (pi: ExtensionApi) {
  let pending: NodeJS.Timeout | undefined;

  pi.on("agent_end", (event) => {
    if (event.willContinue === true) {
      return;
    }
    const text = lastAssistantText(event.messages ?? []);
    const heading = text.match(QUESTION_HEADING);
    if (!heading) {
      return;
    }
    const question = (text.match(QUESTION_LINE)?.[1] ?? heading[1]).trim();
    clearTimeout(pending);
    pending = setTimeout(() => reportBlocked(question), REPORT_DELAY_MS);
    pending.unref?.();
  });

  // An answer typed within the delay starts the next turn; never report over it.
  pi.on("agent_start", () => clearTimeout(pending));
}
