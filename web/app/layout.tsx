import type { Metadata } from "next";
import Link from "next/link";
import { Noto_Sans_KR } from "next/font/google";
import "./globals.css";

const notoSans = Noto_Sans_KR({
  variable: "--font-noto-sans",
  weight: ["400", "500", "700"],
  preload: false,
});

export const metadata: Metadata = {
  title: "Offorby — 대한민국 공직자 한눈에",
  description: "대통령·국무위원·국회의원 목록과 지역구 정보",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className={`${notoSans.variable} antialiased`}>
        <header className="border-b border-line">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
            <Link href="/" className="text-lg font-bold tracking-tight">
              Offorby
            </Link>
            <span className="text-xs text-muted">매일 자동 갱신</span>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
        <footer className="mx-auto max-w-5xl px-4 py-8 text-xs text-muted">
          출처: 열린국회정보 OpenAPI, 정부 부처 누리집
        </footer>
      </body>
    </html>
  );
}
