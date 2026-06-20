import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ODS Chatbot — โรงพยาบาลโพธาราม",
  description:
    "ผู้ช่วยตอบคำถามเรื่องการผ่าตัดแบบวันเดียว (One-Day Surgery) จากคู่มือโรงพยาบาล",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="th">
      <body>{children}</body>
    </html>
  );
}
