"use client";

import { AlertCircle, RefreshCw } from "lucide-react";

export default function GlobalError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    return (
        <html lang="en">
            <body className="flex min-h-screen flex-col items-center justify-center p-6 text-center font-sans">
                <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-red-100 text-red-600 mb-4">
                    <AlertCircle className="h-8 w-8" />
                </div>
                <h2 className="text-xl font-bold tracking-tight mb-2">
                    Application Error
                </h2>
                <p className="max-w-md text-sm text-gray-500 mb-6">
                    {error.message || "A critical error occurred."}
                </p>
                <button
                    onClick={() => reset()}
                    className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
                >
                    <RefreshCw className="h-4 w-4" />
                    Reload application
                </button>
            </body>
        </html>
    );
}
