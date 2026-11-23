/** Root layout: fonts, metadata and the pre-paint theme script. */
import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Scout · ReAct Search Agent",
  description: "A free-model ReAct + deep-research web search agent with verified citations and ambient, topic-aware scenes.",
};

export const viewport: Viewport = {
  themeColor: [{ media: "(prefers-color-scheme: light)", color: "#f5f6f8" }, { media: "(prefers-color-scheme: dark)", color: "#0b0d12" }],
};

/**
 * The inline script runs before first paint and adds `dark` to <html> from the saved choice (or the OS setting),
 * so there is no light-to-dark flash. suppressHydrationWarning: that class differs from the server's HTML on purpose.
 */
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `try{var t=localStorage.getItem("rsa-theme");if(t?t==="dark":matchMedia("(prefers-color-scheme: dark)").matches)document.documentElement.classList.add("dark")}catch(e){}` }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
