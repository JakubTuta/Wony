import type { ReactNode } from 'react';

/** Renders the small slice of Markdown an assistant reply actually uses:
 *  headings, bullet and numbered lists, code, bold, italic and links.
 *
 *  Built as React elements rather than injected HTML, so a reply that quotes a
 *  web page or an email cannot smuggle markup into the page.
 */
export function Markdown({ text }: { text: string }) {
  return <>{blocks(text)}</>;
}

function blocks(text: string): ReactNode[] {
  const lines = text.split('\n');
  const out: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let fence: string[] | null = null;

  const flushList = () => {
    if (!list) return;
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>);
    out.push(
      list.ordered ? (
        <ol key={out.length} className="list-decimal pl-5 space-y-0.5 my-1">
          {items}
        </ol>
      ) : (
        <ul key={out.length} className="list-disc pl-5 space-y-0.5 my-1">
          {items}
        </ul>
      ),
    );
    list = null;
  };

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      if (fence === null) {
        flushList();
        fence = [];
      } else {
        out.push(
          <pre
            key={out.length}
            className="my-1.5 p-2.5 rounded-lg bg-gray-900/90 dark:bg-black/50 text-gray-100
                       text-[12px] overflow-x-auto"
          >
            <code>{fence.join('\n')}</code>
          </pre>,
        );
        fence = null;
      }
      continue;
    }
    if (fence !== null) {
      fence.push(line);
      continue;
    }

    const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      const ordered = Boolean(numbered);
      const content = (bullet ?? numbered)![1];
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push(content);
      continue;
    }

    flushList();

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      out.push(
        <p key={out.length} className="font-semibold mt-1.5 first:mt-0">
          {inline(heading[2])}
        </p>,
      );
      continue;
    }

    if (!line.trim()) {
      out.push(<div key={out.length} className="h-2" />);
      continue;
    }
    out.push(
      <p key={out.length} className="whitespace-pre-wrap">
        {inline(line)}
      </p>,
    );
  }

  flushList();
  if (fence !== null && fence.length) {
    out.push(
      <pre key={out.length} className="my-1.5 p-2.5 rounded-lg bg-gray-900/90 text-gray-100 text-[12px] overflow-x-auto">
        <code>{fence.join('\n')}</code>
      </pre>,
    );
  }
  return out;
}

// One pass over `code`, **bold**, *italic* and [text](url), innermost first so
// bold inside a link still renders.
const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)|(\[[^\]]+\]\((https?:\/\/[^\s)]+)\))/g;

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  INLINE.lastIndex = 0;

  while ((match = INLINE.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const [whole, code, bold, italic, link, href] = match;
    const key = out.length;
    if (code) {
      out.push(
        <code
          key={key}
          className="px-1 py-0.5 rounded bg-gray-200/70 dark:bg-gray-700/60 text-[12px]"
        >
          {code.slice(1, -1)}
        </code>,
      );
    } else if (bold) {
      out.push(<strong key={key}>{bold.slice(2, -2)}</strong>);
    } else if (italic) {
      out.push(<em key={key}>{italic.slice(1, -1)}</em>);
    } else if (link) {
      out.push(
        <a
          key={key}
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          className="text-violet-600 dark:text-violet-400 underline underline-offset-2"
        >
          {link.slice(1, link.indexOf(']'))}
        </a>,
      );
    } else {
      out.push(whole);
    }
    last = match.index + whole.length;
  }

  if (last < text.length) out.push(text.slice(last));
  return out;
}
