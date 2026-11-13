"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { Download, Trash2 } from "lucide-react";
import { AuthUser, loadSession, logout } from "@/lib/auth";
import { api } from "@/lib/api";

// Account page (M6.6, D7): a copy of everything stored about the user, and deletion of the account with all of it.

export default function AccountPage() {
    const router = useRouter();
    const [user, setUser] = useState<AuthUser | null | undefined>(undefined);
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [busy, setBusy] = useState<"export" | "delete" | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        loadSession().then(setUser);
    }, []);

    const download = async () => {
        setBusy("export");
        setError(null);
        try {
            const data = await api("/api/v1/account/export");
            const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
            const link = document.createElement("a");
            link.href = url;
            link.download = "pendu-my-data.json";
            link.click();
            URL.revokeObjectURL(url);
        } catch (e: any) {
            setError(e?.message ?? "Could not prepare your data.");
        } finally {
            setBusy(null);
        }
    };

    const remove = async (event: FormEvent) => {
        event.preventDefault();
        setBusy("delete");
        setError(null);
        try {
            await api("/api/v1/account/delete", { method: "POST", json: { password, confirm } });
            // The account is gone: clear what this browser kept about it, then the session cookies
            try {
                localStorage.removeItem("user_profile");
                sessionStorage.removeItem("user_profile_id");
            } catch {
                // storage unavailable: nothing to clear
            }
            await logout();
            router.push("/");
        } catch (e: any) {
            setError(e?.message ?? "Could not delete the account.");
            setBusy(null);
        }
    };

    if (user === undefined) return <p className="p-8 text-sm text-slate-400">Loading...</p>;
    if (user === null) {
        return (
            <div className="p-8 max-w-3xl mx-auto">
                <div className="p-8 rounded-2xl border border-slate-100 bg-white text-center space-y-3">
                    <p className="text-sm text-slate-600">Sign in to manage your account.</p>
                    <Link href="/login?redirect=/account" className="inline-block px-4 py-2 bg-primary text-white rounded-lg text-sm font-bold">Sign In</Link>
                </div>
            </div>
        );
    }

    const input = "w-full px-3 py-2 rounded-lg border border-slate-200 text-sm font-normal text-slate-800 focus:outline-none focus:ring-2 focus:ring-red-200";

    return (
        <div className="p-8 max-w-3xl mx-auto space-y-8">
            <header className="space-y-1">
                <h1 className="text-3xl font-bold tracking-tight">Your account</h1>
                <p className="text-sm text-slate-500">Signed in as {user.email}</p>
            </header>

            {error && <div role="alert" className="p-4 rounded-xl border border-red-100 bg-red-50 text-sm text-red-700">{error}</div>}

            <section className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm space-y-3">
                <h2 className="text-lg font-bold">Your data</h2>
                <p className="text-sm text-slate-600">
                    Download everything stored about you (account, profile, conversations, applications, drafts) as one
                    file. What is stored and for how long is described on the{" "}
                    <Link href="/privacy" className="text-primary hover:underline">privacy page</Link>.
                </p>
                <button onClick={download} disabled={busy !== null}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-200 text-sm font-bold text-slate-700 disabled:opacity-50">
                    <Download className="h-4 w-4" /> {busy === "export" ? "Preparing..." : "Download my data"}
                </button>
            </section>

            <section className="p-6 rounded-2xl border border-red-100 bg-white shadow-sm space-y-4">
                <h2 className="text-lg font-bold text-red-700">Delete account</h2>
                {user.is_admin ? (
                    <p className="text-sm text-slate-600">
                        Administrator accounts can&apos;t be deleted here. The owner removes them with{" "}
                        <code className="text-xs">scripts/delete_account.py</code>.
                    </p>
                ) : (
                    <form onSubmit={remove} className="space-y-4">
                        <p className="text-sm text-slate-600">
                            This permanently deletes your account, profile, conversations, tracked applications, drafts,
                            uploads and request records. It cannot be undone. Download your data first if you want a copy.
                        </p>
                        <label className="block space-y-1 text-xs font-bold text-slate-500">
                            Your password
                            <input type="password" required autoComplete="current-password" className={input}
                                value={password} onChange={(e) => setPassword(e.target.value)} />
                        </label>
                        <label className="block space-y-1 text-xs font-bold text-slate-500">
                            Type DELETE to confirm
                            <input required autoComplete="off" className={input} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                        </label>
                        <button type="submit" disabled={busy !== null || confirm !== "DELETE" || !password}
                            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-bold disabled:opacity-50">
                            <Trash2 className="h-4 w-4" /> {busy === "delete" ? "Deleting..." : "Delete my account"}
                        </button>
                    </form>
                )}
            </section>
        </div>
    );
}
