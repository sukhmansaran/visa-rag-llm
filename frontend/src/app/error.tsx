"use client";

import { useEffect } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";

export default function ErrorBoundary({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    useEffect(() => {
        console.error("App error boundary caught:", error);
    }, [error]);

    return (
        <div className="flex h-full min-h-[500px] flex-col items-center justify-center p-6 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-destructive/10 text-destructive mb-4">
                <AlertCircle className="h-8 w-8" />
            </div>
            <h2 className="text-xl font-bold tracking-tight text-foreground mb-2">
                Something went wrong
            </h2>
            <p className="max-w-md text-sm text-muted-foreground mb-6">
                {error.message || "An unexpected error occurred while rendering the page."}
            </p>
            <button
                onClick={() => reset()}
                className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 transition-opacity"
            >
                <RefreshCw className="h-4 w-4" />
                Try again
            </button>
        </div>
    );
}
