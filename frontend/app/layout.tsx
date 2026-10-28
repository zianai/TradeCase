import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "TradeCase · 询盘工作台",
  description: "从询盘到有证据支持的客户决策。",
  robots: { index: false, follow: false },
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
