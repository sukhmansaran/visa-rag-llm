import Link from "next/link";
import { FileQuestion, ArrowLeft } from "lucide-react";

export default function NotFound() {
    return (
        <div className="flex h-full min-h-[500px] flex-col items-center justify-center p-6 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted text-muted-foreground mb-4">
                <FileQuestion className="h-8 w-8" />
            </div>
            <h2 className="text-xl font-bold tracking-tight text-foreground mb-2">
                Page Not Found
            </h2>
            <p className="max-w-md text-sm text-muted-foreground mb-6">
                The requested resource could not be found.
            </p>
            <Link
                href="/chat"
                className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 transition-opacity"
            >
                <ArrowLeft className="h-4 w-4" />
                Return to Chat
            </Link>
        </div>
    );
}
