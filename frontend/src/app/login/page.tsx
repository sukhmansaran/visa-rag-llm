"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { login, safeRedirectPath } from "@/lib/auth";
import { ShieldCheck, ArrowRight, Loader2, AlertCircle } from "lucide-react";

function LoginPageForm() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const redirectUrl = safeRedirectPath(searchParams.get("redirect"));

    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        setLoading(true);

        try {
            // The session is kept in httpOnly cookies by /api/auth/login; no token reaches this page
            await login(email, password);
            router.push(redirectUrl);
        } catch (err: any) {
            setError(err.message || "Authentication failed. Please try again.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-12 text-slate-100">
            <div className="w-full max-w-md space-y-8 rounded-2xl border border-slate-800 bg-slate-900 p-8 shadow-2xl">
                <div className="text-center">
                    <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600/20 text-blue-400 border border-blue-500/30">
                        <ShieldCheck className="h-8 w-8 text-blue-400" />
                    </div>
                    <h2 className="mt-5 text-3xl font-extrabold tracking-tight text-white">Sign in to Pendu</h2>
                    <p className="mt-2 text-sm text-slate-400">
                        Deterministic Canadian Immigration Intelligence
                    </p>
                </div>

                {error && (
                    <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-950/40 p-3 text-sm text-red-400">
                        <AlertCircle className="h-5 w-5 shrink-0" />
                        <span>{error}</span>
                    </div>
                )}

                <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
                    <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                            Email address
                        </label>
                        <input
                            type="email"
                            required
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            placeholder="you@example.com"
                            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                        />
                    </div>

                    <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                            Password
                        </label>
                        <input
                            type="password"
                            required
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="••••••••••••"
                            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={loading}
                        className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3.5 text-sm font-semibold text-white shadow-lg transition-all hover:bg-blue-500 disabled:opacity-50"
                    >
                        {loading ? (
                            <>
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Authenticating...
                            </>
                        ) : (
                            <>
                                Sign In
                                <ArrowRight className="h-4 w-4" />
                            </>
                        )}
                    </button>
                </form>

                <div className="text-center text-xs text-slate-400">
                    Don&apos;t have an account?{" "}
                    <Link
                        href={`/signup?redirect=${encodeURIComponent(redirectUrl)}`}
                        className="font-medium text-blue-400 hover:text-blue-300 hover:underline"
                    >
                        Create an account
                    </Link>
                </div>
            </div>
        </div>
    );
}

// useSearchParams() requires a Suspense boundary for static prerendering (Next.js 15)
export default function LoginPage() {
    return (
        <Suspense fallback={null}>
            <LoginPageForm />
        </Suspense>
    );
}
