"use client";

import { useState } from "react";
import Link from "next/link";
import {
  layers,
  sessions,
  type LayerKey,
} from "@/content/sessions";

const layerOrder: LayerKey[] = ["L1", "L2", "L3", "L4", "L5", "L6"];

export default function LayersPage() {
  const [expandedLayers, setExpandedLayers] = useState<Set<LayerKey>>(
    new Set(layerOrder)
  );

  const toggleLayer = (key: LayerKey) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <h1 className="text-3xl font-bold text-zinc-900 dark:text-zinc-50 mb-2">
        架构层次
      </h1>
      <p className="text-zinc-500 dark:text-zinc-400 mb-10">
        AI Agent 的 6 个核心架构层，从工具执行到开放生态。
      </p>

      <div className="space-y-4">
        {layerOrder.map((key) => {
          const layer = layers[key];
          const layerSessions = sessions.filter((s) => s.layer === key);
          const isExpanded = expandedLayers.has(key);

          return (
            <div
              key={key}
              className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden"
            >
              {/* Layer header */}
              <button
                onClick={() => toggleLayer(key)}
                className="w-full flex items-center justify-between p-5 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`w-4 h-4 rounded-full ${layer.dotColor}`}
                  />
                  <div>
                    <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                      {layer.key} {layer.name}
                    </h2>
                    <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
                      {layer.description}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="text-xs text-zinc-400 dark:text-zinc-500">
                    {layerSessions.length} 节课
                  </span>
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className={`text-zinc-400 transition-transform ${
                      isExpanded ? "rotate-180" : ""
                    }`}
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </div>
              </button>

              {/* Session cards */}
              {isExpanded && layerSessions.length > 0 && (
                <div className="border-t border-zinc-100 dark:border-zinc-800 p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {layerSessions.map((session) => (
                    <Link
                      key={session.id}
                      href={`/session/${session.id}`}
                      className="group p-4 rounded-lg border border-zinc-100 dark:border-zinc-800 hover:border-zinc-200 dark:hover:border-zinc-700 hover:shadow-sm transition-all"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-mono text-zinc-400 dark:text-zinc-500">
                          {session.id.toUpperCase()}
                        </span>
                        <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                          {session.title}
                        </h3>
                      </div>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-2">
                        {session.subtitle}
                      </p>
                      <div className="flex items-center gap-3 text-xs text-zinc-400 dark:text-zinc-500">
                        <span>{session.loc} 行</span>
                        <span>{session.tools} 工具</span>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
