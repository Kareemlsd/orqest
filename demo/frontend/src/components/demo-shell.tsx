"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import {
  MessageSquare,
  PenSquare,
  ListChecks,
  ImageIcon,
  BookOpen,
  Home,
  Sparkles,
} from "lucide-react";

const NAV = [
  { href: "/", label: "Home", icon: Home },
  {
    href: "/workbench",
    label: "Workbench",
    icon: Sparkles,
    featured: true,
  },
  { href: "/demos/chat", label: "Chat", icon: MessageSquare },
  { href: "/demos/artifact", label: "Artifact Studio", icon: PenSquare },
  { href: "/demos/tasks", label: "Task Planner", icon: ListChecks },
  { href: "/demos/multimodal", label: "Multimodal", icon: ImageIcon },
  { href: "/demos/research", label: "Research", icon: BookOpen },
];

export function DemoShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* Sidebar */}
      <aside className="w-60 border-r border-border/60 flex flex-col">
        <div className="p-4 border-b border-border/60">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded bg-teal-700 flex items-center justify-center text-sm font-bold text-white">
              O
            </div>
            <span className="font-semibold tracking-tight">Orqest</span>
          </Link>
        </div>

        <nav className="flex-1 p-2 space-y-0.5">
          {NAV.map(({ href, label, icon: Icon, featured }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                  active
                    ? "bg-accent text-accent-foreground"
                    : featured
                      ? "text-teal-400 hover:bg-teal-950/30"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{label}</span>
                {featured && (
                  <span className="ml-auto text-[9px] uppercase tracking-wider font-semibold opacity-70">
                    New
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        <div className="p-4 border-t border-border/60 text-xs text-muted-foreground">
          <p>pydantic-ai + AI SDK</p>
          <p className="mt-0.5 opacity-70">v0.1.0 — demo</p>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="border-b border-border/60 px-6 py-3.5 flex items-center justify-between">
          <div>
            <h1 className="text-sm font-semibold tracking-tight">{title}</h1>
            {subtitle && (
              <p className="text-xs text-muted-foreground">{subtitle}</p>
            )}
          </div>
        </header>
        <div className="flex-1 overflow-hidden">{children}</div>
      </main>
    </div>
  );
}
