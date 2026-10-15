"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { safeRedirectPath, signup } from "@/lib/auth";
import { UserPlus, ArrowRight, Loader2, AlertCircle } from "lucide-react";

function SignupPageForm() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const redirectUrl = safeRedirectPath(searchParams.get("redirect"));

    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);

        if (password.length < 10 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) {
            setError("Password must be at least 10 characters and include a letter and a number.");
            return;
        }

        if (password !== confirmPassword) {
            setError("Passwords do not match.");
            return;
        }

        setLoading(true);

        try {
            // The session is kept in httpOnly cookies by /api/auth/signup; no token reaches this page
            await signup(email, password);
            router.push(redirectUrl);
        } catch (err: any) {
            setError(err.message || "An error occurred while creating your account.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-12 text-slate-100">
            <div className="w-full max-w-md space-y-8 rounded-2xl border border-slate-800 bg-slate-900 p-8 shadow-2xl">
                <div className="text-center">
                    <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600/20 text-blue-400 border border-blue-500/30">
                        <UserPlus className="h-8 w-8 text-blue-400" />
                    </div>
                    <h2 className="mt-5 text-3xl font-extrabold tracking-tight text-white">Create an account</h2>
                    <p className="mt-2 text-sm text-slate-400">
                        Get started with verified IRCC guidance
                    </p>
                </div>

                {error && (
                    <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-950/40 p-3 text-sm text-red-400">
                        <AlertCircle className="h-5 w-5 shrink-0" />
                        <span>{error}</span>
                    </div>
                )}

                <form className="mt-8 space-y-4" onSubmit={handleSubmit}>
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
                            Password (min. 10 characters, letters and numbers)
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

                    <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                            Confirm Password
                        </label>
                        <input
                            type="password"
                            required
                            value={confirmPassword}
                            onChange={(e) => setConfirmPassword(e.target.value)}
                            placeholder="••••••••••••"
                            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={loading}
                        className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3.5 text-sm font-semibold text-white shadow-lg transition-all hover:bg-blue-500 disabled:opacity-50 mt-2"
                    >
                        {loading ? (
                            <>
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Creating Account...
                            </>
                        ) : (
                            <>
                                Sign Up
                                <ArrowRight className="h-4 w-4" />
                            </>
                        )}
                    </button>
                </form>

                <div className="text-center text-xs text-slate-400">
                    Already have an account?{" "}
                    <Link
                        href={`/login?redirect=${encodeURIComponent(redirectUrl)}`}
                        className="font-medium text-blue-400 hover:text-blue-300 hover:underline"
                    >
                        Sign in
                    </Link>
                </div>
            </div>
        </div>
    );
}

// useSearchParams() requires a Suspense boundary for static prerendering (Next.js 15)
export default function SignupPage() {
    return (
        <Suspense fallback={null}>
            <SignupPageForm />
        </Suspense>
    );
}
