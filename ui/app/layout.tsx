import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "seedwright",
  description: "Reproducible synthetic data, from blueprint to database",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <span className="logo">seedwright</span>
          <span className="tagline">reproducible synthetic data</span>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
