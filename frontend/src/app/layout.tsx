import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
    title: "Pendu | Deterministic Visa RAG",
    description: "High-accuracy, low-cost visa and study abroad assistant.",
};

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en">
            <body className={inter.className}>
                <div className="flex bg-background text-foreground h-screen overflow-hidden">
                    <Sidebar />
                    <main className="flex-1 min-h-screen overflow-y-auto w-full">
                        {children}
                    </main>
                </div>
            </body>
        </html>
    );
}
