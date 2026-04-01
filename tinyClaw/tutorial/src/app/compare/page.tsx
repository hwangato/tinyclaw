"use client";

import { useState } from "react";
import { sessions, layers } from "@/content/sessions";

export default function ComparePage() {
  const [versionA, setVersionA] = useState(sessions[0].id);
  const [versionB, setVersionB] = useState(
    sessions[sessions.length - 1].id
  );

  const sessionA = sessions.find((s) => s.id === versionA)!;
  const sessionB = sessions.find((s) => s.id === versionB)!;

  const idxA = sessions.findIndex((s) => s.id === versionA);
  const idxB = sessions.findIndex((s) => s.id === versionB);
  const [startIdx, endIdx] =
    idxA <= idxB ? [idxA, idxB] : [idxB, idxA];
  const betweenSessions = sessions.slice(startIdx, endIdx + 1);

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold text-zinc-900 dark:text-zinc-50 mb-2">
        版本对比
      </h1>
      <p className="text-zinc-500 dark:text-zinc-400 mb-8">
        选择两个版本，查看它们之间的变化。
      </p>

      {/* Dropdowns */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 mb-10">
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            版本 A:
          </label>
          <select
            value={versionA}
            onChange={(e) => setVersionA(e.target.value)}
            className="px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id.toUpperCase()} - {s.title}
              </option>
            ))}
          </select>
        </div>

        <span className="text-zinc-400 hidden sm:block">vs</span>

        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            版本 B:
          </label>
          <select
            value={versionB}
            onChange={(e) => setVersionB(e.target.value)}
            className="px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id.toUpperCase()} - {s.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Side-by-side comparison */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-10">
        <ComparisonCard session={sessionA} label="版本 A" />
        <ComparisonCard session={sessionB} label="版本 B" />
      </div>

      {/* Changes between versions */}
      <section>
        <h2 className="text-xl font-bold text-zinc-900 dark:text-zinc-100 mb-4">
          变更历程 ({betweenSessions.length} 步)
        </h2>
        <div className="space-y-3">
          {betweenSessions.map((session) => {
            const layer = layers[session.layer];
            return (
              <div
                key={session.id}
                className="flex items-center gap-4 p-3 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900"
              >
                <span
                  className={`w-2.5 h-2.5 rounded-full shrink-0 ${layer.dotColor}`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-zinc-400 dark:text-zinc-500">
                      {session.id.toUpperCase()}
                    </span>
                    <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                      {session.title}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400 truncate">
                    {session.insight}
                  </p>
                </div>
                <div className="flex items-center gap-3 shrink-0 text-xs text-zinc-400 dark:text-zinc-500">
                  <span>{session.loc} 行</span>
                  <span>{session.tools} 工具</span>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Summary stats */}
      <section className="mt-10 p-6 rounded-xl bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-800">
        <h3 className="text-lg font-bold text-zinc-900 dark:text-zinc-100 mb-4">
          变化摘要
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard
            label="代码增长"
            value={`+${Math.abs(sessionB.loc - sessionA.loc)} 行`}
          />
          <StatCard
            label="工具增长"
            value={`+${Math.abs(sessionB.tools - sessionA.tools)} 个`}
          />
          <StatCard
            label="涉及步骤"
            value={`${betweenSessions.length} 步`}
          />
          <StatCard
            label="覆盖层次"
            value={`${new Set(betweenSessions.map((s) => s.layer)).size} 层`}
          />
        </div>
      </section>
    </div>
  );
}

function ComparisonCard({
  session,
  label,
}: {
  session: (typeof sessions)[number];
  label: string;
}) {
  const layer = layers[session.layer];
  return (
    <div className="p-5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
      <div className="text-xs text-zinc-400 dark:text-zinc-500 mb-2">
        {label}
      </div>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-mono text-zinc-400">
          {session.id.toUpperCase()}
        </span>
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${layer.bgColor} ${layer.textColor}`}
        >
          {layer.key}
        </span>
      </div>
      <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 mb-1">
        {session.title}
      </h3>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-3">
        {session.subtitle}
      </p>
      <div className="flex gap-4 text-sm">
        <span className="text-zinc-600 dark:text-zinc-400">
          <strong className="text-zinc-900 dark:text-zinc-100">
            {session.loc}
          </strong>{" "}
          行
        </span>
        <span className="text-zinc-600 dark:text-zinc-400">
          <strong className="text-zinc-900 dark:text-zinc-100">
            {session.tools}
          </strong>{" "}
          工具
        </span>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center">
      <div className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
        {value}
      </div>
      <div className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
        {label}
      </div>
    </div>
  );
}
