import Link from "next/link";
import { notFound } from "next/navigation";
import { CodeBlock } from "@/components/CodeBlock";
import { ChangesTable } from "@/components/ChangesTable";
import {
  getSession,
  getAdjacentSessions,
  layers,
  sessions,
} from "@/content/sessions";

export function generateStaticParams() {
  return sessions.map((s) => ({ id: s.id }));
}

export default async function SessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const session = getSession(id);

  if (!session) {
    notFound();
  }

  const { prev, next } = getAdjacentSessions(id);
  const layer = layers[session.layer];

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Category badge */}
      <div className="mb-4">
        <span
          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${layer.bgColor} ${layer.textColor}`}
        >
          <span className={`w-2 h-2 rounded-full ${layer.dotColor}`} />
          {layer.key} {layer.name}
        </span>
      </div>

      {/* Title */}
      <h1 className="text-3xl sm:text-4xl font-bold text-zinc-900 dark:text-zinc-50 mb-2">
        {session.id.toUpperCase()}: {session.title}
      </h1>
      <p className="text-lg text-zinc-500 dark:text-zinc-400 mb-6">
        {session.subtitle}
      </p>

      {/* Stats badges */}
      <div className="flex flex-wrap gap-3 mb-8">
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-sm text-zinc-700 dark:text-zinc-300">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <polyline points="16,18 22,18 22,12" />
            <polyline points="8,6 2,6 2,12" />
            <line x1="2" y1="12" x2="22" y2="12" />
          </svg>
          {session.loc} 行代码
        </span>
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-sm text-zinc-700 dark:text-zinc-300">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
          </svg>
          {session.tools} 个工具
        </span>
      </div>

      {/* Insight callout */}
      <div className="p-4 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 mb-10">
        <div className="flex items-start gap-3">
          <span className="text-blue-500 dark:text-blue-400 mt-0.5 shrink-0">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="16" x2="12" y2="12" />
              <line x1="12" y1="8" x2="12.01" y2="8" />
            </svg>
          </span>
          <p className="text-sm text-blue-800 dark:text-blue-300 leading-relaxed font-medium">
            {session.insight}
          </p>
        </div>
      </div>

      {/* Problem section */}
      <section className="mb-10">
        <h2 className="text-xl font-bold text-zinc-900 dark:text-zinc-100 mb-3 flex items-center gap-2">
          <span className="text-red-500">&#9679;</span> 问题
        </h2>
        <p className="text-zinc-600 dark:text-zinc-400 leading-relaxed">
          {session.problem}
        </p>
      </section>

      {/* Solution section */}
      <section className="mb-10">
        <h2 className="text-xl font-bold text-zinc-900 dark:text-zinc-100 mb-3 flex items-center gap-2">
          <span className="text-green-500">&#9679;</span> 解决方案
        </h2>
        <CodeBlock
          code={session.solution}
          language="text"
          filename="架构图"
          showLineNumbers={false}
        />
      </section>

      {/* How It Works section */}
      <section className="mb-10">
        <h2 className="text-xl font-bold text-zinc-900 dark:text-zinc-100 mb-6 flex items-center gap-2">
          <span className="text-blue-500">&#9679;</span> 实现步骤
        </h2>
        <div className="space-y-8">
          {session.howItWorks.map((step) => (
            <div key={step.step} className="relative pl-10">
              <div className="absolute left-0 top-0 w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400 flex items-center justify-center text-sm font-bold">
                {step.step}
              </div>
              <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100 mb-1">
                {step.title}
              </h3>
              <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-3 leading-relaxed">
                {step.description}
              </p>
              {step.code && (
                <CodeBlock
                  code={step.code}
                  language="python"
                  showLineNumbers={false}
                />
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Changes table */}
      <section className="mb-10">
        <h2 className="text-xl font-bold text-zinc-900 dark:text-zinc-100 mb-3 flex items-center gap-2">
          <span className="text-amber-500">&#9679;</span> 变更对比
        </h2>
        <ChangesTable changes={session.changes} />
      </section>

      {/* Try It Out section */}
      <section className="mb-10">
        <h2 className="text-xl font-bold text-zinc-900 dark:text-zinc-100 mb-3 flex items-center gap-2">
          <span className="text-purple-500">&#9679;</span> 动手试试
        </h2>
        <CodeBlock
          code={session.tryIt.join("\n")}
          language="bash"
          filename="终端"
          showLineNumbers={false}
        />
      </section>

      {/* Previous / Next navigation */}
      <nav className="flex items-center justify-between pt-8 border-t border-zinc-200 dark:border-zinc-800">
        {prev ? (
          <Link
            href={`/session/${prev.id}`}
            className="group flex flex-col items-start gap-1 text-sm"
          >
            <span className="text-zinc-400 dark:text-zinc-500 text-xs">
              ← 上一节
            </span>
            <span className="text-zinc-700 dark:text-zinc-300 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors font-medium">
              {prev.id.toUpperCase()}: {prev.title}
            </span>
          </Link>
        ) : (
          <div />
        )}
        {next ? (
          <Link
            href={`/session/${next.id}`}
            className="group flex flex-col items-end gap-1 text-sm"
          >
            <span className="text-zinc-400 dark:text-zinc-500 text-xs">
              下一节 →
            </span>
            <span className="text-zinc-700 dark:text-zinc-300 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors font-medium">
              {next.id.toUpperCase()}: {next.title}
            </span>
          </Link>
        ) : (
          <div />
        )}
      </nav>
    </div>
  );
}
