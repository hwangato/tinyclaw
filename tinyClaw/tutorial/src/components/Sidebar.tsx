"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { sessions, layers, type LayerKey } from "@/content/sessions";

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

const layerOrder: LayerKey[] = ["L1", "L2", "L3", "L4", "L5", "L6"];

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();

  const sessionsByLayer = layerOrder.map((key) => ({
    layer: layers[key],
    sessions: sessions.filter((s) => s.layer === key),
  }));

  return (
    <>
      {/* Overlay for mobile */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed top-14 left-0 z-40 h-[calc(100vh-3.5rem)] w-72 bg-white dark:bg-zinc-900 border-r border-zinc-200 dark:border-zinc-800 overflow-y-auto transition-transform duration-200 lg:translate-x-0 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <nav className="p-4 space-y-6">
          <Link
            href="/"
            className="block text-sm font-medium text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors mb-4"
            onClick={onClose}
          >
            ← 返回首页
          </Link>

          {sessionsByLayer.map(({ layer, sessions: layerSessions }) => {
            if (layerSessions.length === 0) return null;
            return (
              <div key={layer.key}>
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className={`w-2.5 h-2.5 rounded-full ${layer.dotColor}`}
                  />
                  <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                    {layer.key} {layer.name}
                  </span>
                </div>
                <ul className="space-y-1">
                  {layerSessions.map((session) => {
                    const href = `/session/${session.id}`;
                    const isActive = pathname === href;
                    return (
                      <li key={session.id}>
                        <Link
                          href={href}
                          onClick={onClose}
                          className={`flex items-center justify-between px-3 py-2 rounded-md text-sm transition-colors ${
                            isActive
                              ? "bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 font-medium"
                              : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200"
                          }`}
                        >
                          <span className="flex items-center gap-2 min-w-0">
                            <span className="text-xs text-zinc-400 dark:text-zinc-500 font-mono shrink-0">
                              {session.id.toUpperCase()}
                            </span>
                            <span className="truncate">{session.title}</span>
                          </span>
                          <span className="text-xs text-zinc-400 dark:text-zinc-500 shrink-0 ml-2">
                            {session.loc}行
                          </span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
