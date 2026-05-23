import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Polymath",
  description: "General-purpose autonomous agent powered by Orqest.",
};

/**
 * Root layout — forces dark mode everywhere. Polymath is a workspace tool,
 * always dark, per the numatics-ai design-decisions precedent. Fonts load
 * via the @import at the top of globals.css (Google Fonts CDN).
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-background text-foreground font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
