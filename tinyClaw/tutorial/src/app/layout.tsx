import type { Metadata } from "next";
import { ThemeProvider } from "@/components/ThemeProvider";
import { LayoutShell } from "@/components/LayoutShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Learn TinyClaw - 从零构建 Python 版 AI Agent",
  description:
    "12 个递进式教程，从 25 行代码到 520 行，带你掌握 AI Agent 的核心架构。涵盖工具调用、多轮记忆、ReAct 推理、多 Agent 协作、MCP 协议等关键技术。",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" className="h-full antialiased" suppressHydrationWarning>
      <body className="min-h-full flex flex-col">
        <ThemeProvider>
          <LayoutShell>{children}</LayoutShell>
        </ThemeProvider>
      </body>
    </html>
  );
}
