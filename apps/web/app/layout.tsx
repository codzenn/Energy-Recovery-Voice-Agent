import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Energy Recovery Agent",
  description: "Local synthetic-data voice agent foundation",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
