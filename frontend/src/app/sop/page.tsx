"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { Info, Save, Wand2 } from "lucide-react";
import { isAuthenticated } from "@/lib/auth";
import { api, formatDate } from "@/lib/api";

// SOP drafts (M6.4): written by the local model from the user's saved profile (POST /documents/sop/generate),
// kept on the server, and edited and saved here. No sample text: an empty editor means there is no draft yet.

interface SopDocument {
    id: number;
    content: string;
    version: number;
    updated_at: string;
}

async function latestDraft(): Promise<SopDocument | null> {
    const list = await api<{ id: number }[]>("/api/v1/documents?document_type=sop"); // newest first
    return list.length ? api<SopDocument>(`/api/v1/documents/sop/${list[0].id}`) : null;
}

export default function SopGeneratorPage() {
    const [signedIn, setSignedIn] = useState<boolean | null>(null);
    const [doc, setDoc] = useState<SopDocument | null>(null);
    const [draft, setDraft] = useState("");
    const [university, setUniversity] = useState("");
    const [program, setProgram] = useState("");
    const [extra, setExtra] = useState("");
    const [busy, setBusy] = useState<"loading" | "generating" | "saving" | null>("loading");
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const show = useCallback((document: SopDocument | null) => {
        setDoc(document);
        setDraft(document?.content ?? "");
    }, []);

    useEffect(() => {
        const authed = isAuthenticated();
        setSignedIn(authed);
        if (!authed) {
            setBusy(null);
            return;
        }
        latestDraft()
            .then(show)
            .catch((e) => (e?.status === 401 ? setSignedIn(false) : setError(e?.message ?? "Could not load your draft.")))
            .finally(() => setBusy(null));
    }, [show]);

    const generate = async (event: FormEvent) => {
        event.preventDefault();
        if (draft.trim() && draft !== (doc?.content ?? "") && !window.confirm("Your unsaved edits will be replaced by the new draft. Continue?")) return;
        setBusy("generating");
        setError(null);
        setNotice(null);
        const before = doc?.id ?? null;
        try {
            show(await api<SopDocument>("/api/v1/documents/sop/generate", {
                method: "POST",
                json: { university: university.trim(), program: program.trim(), additional_info: extra.trim() || null },
            }));
            setNotice("Draft written and saved. Read it carefully and make it your own before using it.");
        } catch (e: any) {
            // A long draft can outlast the connection while the server still finishes and stores it
            const stored = e?.status === 0 || e?.status >= 504 ? await latestDraft().catch(() => null) : null;
            if (stored && stored.id !== before) {
                show(stored);
                setNotice("Draft written and saved.");
            } else {
                setError(e?.message ?? "The draft could not be written.");
            }
        } finally {
            setBusy(null);
        }
    };

    const save = async () => {
        if (!doc) return;
        setBusy("saving");
        setError(null);
        try {
            show(await api<SopDocument>(`/api/v1/documents/sop/${doc.id}`, { method: "PUT", json: { content: draft } }));
            setNotice("Saved.");
        } catch (e: any) {
            setError(e?.message ?? "Could not save the draft.");
        } finally {
            setBusy(null);
        }
    };

    const input = "w-full px-3 py-2 rounded-lg border border-slate-200 text-sm font-normal text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20";
    const edited = doc !== null && draft !== doc.content;

    if (signedIn === false) {
        return (
            <div className="p-8 max-w-3xl mx-auto">
                <div className="p-8 rounded-2xl border border-slate-100 bg-white text-center space-y-3">
                    <p className="text-sm text-slate-600">Sign in to write and keep a Statement of Purpose draft.</p>
                    <Link href="/login?redirect=/sop" className="inline-block px-4 py-2 bg-primary text-white rounded-lg text-sm font-bold">
                        Sign In
                    </Link>
                </div>
            </div>
        );
    }

    return (
        <div className="p-8 space-y-8 max-w-6xl mx-auto">
            <header className="flex justify-between items-center">
                <div className="space-y-1">
                    <h1 className="text-3xl font-bold tracking-tight">Statement of Purpose</h1>
                    <p className="text-slate-500 text-sm">A first draft written from your saved profile, for you to edit.</p>
                </div>
                <button
                    onClick={save}
                    disabled={!edited || busy !== null}
                    className="flex items-center gap-2 px-4 py-2 border border-slate-100 bg-white rounded-xl shadow-sm hover:bg-slate-50 transition-colors text-xs font-bold disabled:opacity-50"
                >
                    <Save className="h-3 w-3" /> {busy === "saving" ? "Saving..." : "Save Edits"}
                </button>
            </header>

            {error && <div role="alert" className="p-4 rounded-xl border border-red-100 bg-red-50 text-sm text-red-700">{error}</div>}
            {notice && !error && <div role="status" className="p-4 rounded-xl border border-green-100 bg-green-50 text-sm text-green-700">{notice}</div>}

            <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                <div className="lg:col-span-3 h-[calc(100vh-250px)] min-h-96">
                    <div className="h-full rounded-2xl border border-slate-100 bg-white shadow-sm overflow-hidden flex flex-col">
                        <div className="px-4 py-3 border-b border-slate-50 bg-slate-50/50 flex justify-between items-center">
                            <span className="text-[10px] uppercase font-black text-slate-400">
                                {doc ? `Draft, version ${doc.version}, saved ${formatDate(doc.updated_at)}${edited ? " (unsaved edits)" : ""}` : "No draft yet"}
                            </span>
                        </div>
                        <textarea
                            className="flex-1 w-full p-8 resize-none focus:outline-none text-slate-800 leading-relaxed font-serif text-lg disabled:bg-slate-50"
                            placeholder={busy === "loading" ? "Loading your draft..." : busy === "generating"
                                ? "Writing your draft. This runs on a local model and can take several minutes; keep this page open."
                                : "No draft yet. Enter the university and program on the right and choose Write Draft."}
                            value={draft}
                            disabled={!doc || busy === "generating"}
                            onChange={(e) => setDraft(e.target.value)}
                        />
                    </div>
                </div>

                <div className="space-y-6">
                    <form onSubmit={generate} className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm space-y-4">
                        <label className="block space-y-1 text-xs font-bold text-slate-500">
                            University or school
                            <input required maxLength={200} className={input} value={university} onChange={(e) => setUniversity(e.target.value)} />
                        </label>
                        <label className="block space-y-1 text-xs font-bold text-slate-500">
                            Program
                            <input required maxLength={200} className={input} value={program} onChange={(e) => setProgram(e.target.value)} />
                        </label>
                        <label className="block space-y-1 text-xs font-bold text-slate-500">
                            Anything to include (optional)
                            <textarea maxLength={2000} rows={3} className={input} value={extra} onChange={(e) => setExtra(e.target.value)} />
                        </label>
                        <button
                            type="submit"
                            disabled={busy !== null}
                            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary text-white rounded-xl shadow-lg shadow-primary/20 hover:bg-primary/90 transition-all font-bold text-xs disabled:opacity-50"
                        >
                            <Wand2 className="h-3 w-3" /> {busy === "generating" ? "Writing (several minutes)..." : doc ? "Write a New Draft" : "Write Draft"}
                        </button>
                    </form>

                    <div className="p-6 rounded-2xl bg-slate-900 text-white space-y-3">
                        <h4 className="font-bold flex items-center gap-2 text-blue-400 text-xs uppercase tracking-widest">
                            <Info className="h-4 w-4" /> Before you use it
                        </h4>
                        <ul className="space-y-2 text-[11px] text-slate-300 leading-relaxed list-disc pl-4">
                            <li>The draft is built from your <Link href="/onboarding" className="text-blue-400 hover:underline">profile</Link>; details you haven&apos;t entered are not in it.</li>
                            <li>It is a starting point written by an AI model. It is not checked against official sources and may contain mistakes.</li>
                            <li>Check every fact about you and the program, and rewrite it in your own words.</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    );
}
