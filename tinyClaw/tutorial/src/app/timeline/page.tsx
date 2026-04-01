import Link from "next/link";
import { sessions, layers } from "@/content/sessions";

export default function TimelinePage() {
  const maxLoc = Math.max(...sessions.map((s) => s.loc));

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold text-zinc-900 dark:text-zinc-50 mb-2">
        学习时间线
      </h1>
      <p className="text-zinc-500 dark:text-zinc-400 mb-10">
        从 25 行到 520 行，见证 Agent 的成长历程。
      </p>

      <div className="relative">
        {/* Vertical line */}
        <div className="absolute left-5 top-0 bottom-0 w-0.5 bg-zinc-200 dark:bg-zinc-800" />

        <div className="space-y-0">
          {sessions.map((session, idx) => {
            const layer = layers[session.layer];
            const barWidth = Math.round((session.loc / maxLoc) * 100);

            return (
              <div key={session.id} className="relative pl-14 pb-10">
                {/* Node dot */}
                <div
                  className={`absolute left-3.5 top-1 w-4 h-4 rounded-full border-2 border-white dark:border-zinc-900 ${layer.dotColor} z-10`}
                />

                {/* Session number */}
                <div className="absolute left-0 top-0 w-2.5 text-right">
                  <span className="text-[10px] text-zinc-400 dark:text-zinc-600 font-mono">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                </div>

                <Link
                  href={`/session/${session.id}`}
                  className="group block p-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:border-zinc-300 dark:hover:border-zinc-700 hover:shadow-sm transition-all"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-zinc-400 dark:text-zinc-500">
                        {session.id.toUpperCase()}
                      </span>
                      <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                        {session.title}
                      </h3>
                    </div>
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${layer.bgColor} ${layer.textColor}`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${layer.dotColor}`}
                      />
                      {layer.key}
                    </span>
                  </div>

                  <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-3">
                    {session.subtitle}
                  </p>

                  {/* LOC bar */}
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-2 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${layer.dotColor} opacity-60`}
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                    <span className="text-xs text-zinc-500 dark:text-zinc-400 font-mono shrink-0 w-14 text-right">
                      {session.loc} 行
                    </span>
                  </div>
                </Link>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
