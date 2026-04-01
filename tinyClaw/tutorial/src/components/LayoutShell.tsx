"use client";

import { useState, type ReactNode } from "react";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

export function LayoutShell({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <>
      <Header onMenuToggle={() => setSidebarOpen((prev) => !prev)} />
      <div className="flex flex-1">
        <Sidebar
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />
        <main className="flex-1 lg:ml-72 min-h-[calc(100vh-3.5rem)]">
          {children}
        </main>
      </div>
    </>
  );
}
