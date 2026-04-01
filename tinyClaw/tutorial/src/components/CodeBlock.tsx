import { codeToHtml } from "shiki";

interface CodeBlockProps {
  code: string;
  language?: string;
  filename?: string;
  showLineNumbers?: boolean;
}

export async function CodeBlock({
  code,
  language = "python",
  filename,
  showLineNumbers = true,
}: CodeBlockProps) {
  const html = await codeToHtml(code, {
    lang: language,
    themes: {
      light: "github-light",
      dark: "github-dark",
    },
    defaultColor: false,
  });

  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-700 overflow-hidden my-4">
      {filename && (
        <div className="flex items-center justify-between px-4 py-2 bg-zinc-100 dark:bg-zinc-800 border-b border-zinc-200 dark:border-zinc-700">
          <span className="text-sm text-zinc-600 dark:text-zinc-400 font-mono">
            {filename}
          </span>
          <CopyButton code={code} />
        </div>
      )}
      {!filename && (
        <div className="flex justify-end px-4 py-1 bg-zinc-100 dark:bg-zinc-800 border-b border-zinc-200 dark:border-zinc-700">
          <CopyButton code={code} />
        </div>
      )}
      <div
        className={`overflow-x-auto text-sm [&_pre]:p-4 [&_pre]:m-0 ${
          showLineNumbers ? "[&_.line]:before:content-[counter(line)] [&_.line]:before:counter-increment-[line] [&_.line]:before:mr-4 [&_.line]:before:text-zinc-400 [&_.line]:before:text-right [&_.line]:before:inline-block [&_.line]:before:w-4 [&_code]:counter-reset-[line]" : ""
        }`}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}

function CopyButton({ code }: { code: string }) {
  return (
    <button
      data-copy={code}
      className="copy-btn text-xs px-2 py-1 rounded text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
      title="复制代码"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      </svg>
    </button>
  );
}
