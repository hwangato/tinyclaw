import Link from "next/link";
import { sessions, layers } from "@/content/sessions";

export default function HomePage() {
  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      {/* Hero section */}
      <section className="text-center mb-16">
        <h1 className="text-4xl sm:text-5xl font-bold text-zinc-900 dark:text-zinc-50 mb-4 tracking-tight">
          从零构建 Python 版 AI Agent
        </h1>
        <p className="text-lg sm:text-xl text-zinc-500 dark:text-zinc-400 max-w-2xl mx-auto leading-relaxed">
          12 个递进式教程，从 25 行到 520 行代码，
          <br className="hidden sm:block" />
          掌握 AI Agent 的完整架构与核心技术。
        </p>
        <div className="flex flex-wrap justify-center gap-3 mt-8">
          {(["L1", "L2", "L3", "L4", "L5", "L6"] as const).map((key) => {
            const layer = layers[key];
            return (
              <span
                key={key}
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${layer.bgColor} ${layer.textColor}`}
              >
                <span className={`w-2 h-2 rounded-full ${layer.dotColor}`} />
                {layer.key} {layer.name}
              </span>
            );
          })}
        </div>
      </section>

      {/* Session cards grid */}
      <section>
        <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-6">
          全部教程
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {sessions.map((session) => {
            const layer = layers[session.layer];
            return (
              <Link
                key={session.id}
                href={`/session/${session.id}`}
                className="group block p-5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:border-zinc-300 dark:hover:border-zinc-700 hover:shadow-md transition-all"
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-mono text-zinc-400 dark:text-zinc-500">
                    {session.id.toUpperCase()}
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${layer.bgColor} ${layer.textColor}`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${layer.dotColor}`}
                    />
                    {layer.key}
                  </span>
                </div>

                <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100 mb-1 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                  {session.title}
                </h3>
                <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-3">
                  {session.subtitle}
                </p>

                <div className="flex items-center gap-3 mb-3">
                  <span className="inline-flex items-center gap-1 text-xs text-zinc-500 dark:text-zinc-400">
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="12"
                      height="12"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <polyline points="16,18 22,18 22,12" />
                      <polyline points="8,6 2,6 2,12" />
                      <line x1="2" y1="12" x2="22" y2="12" />
                    </svg>
                    {session.loc} 行
                  </span>
                  <span className="inline-flex items-center gap-1 text-xs text-zinc-500 dark:text-zinc-400">
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="12"
                      height="12"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                    </svg>
                    {session.tools} 工具
                  </span>
                </div>

                <blockquote className="text-xs text-zinc-500 dark:text-zinc-400 italic border-l-2 border-zinc-200 dark:border-zinc-700 pl-3 leading-relaxed">
                  {session.insight}
                </blockquote>
              </Link>
            );
          })}
        </div>
      </section>
    </div>
  );
}
