"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { CalendarDays, ClipboardList, Plus, Trash2 } from "lucide-react";
import { isAuthenticated } from "@/lib/auth";
import { api, formatDate } from "@/lib/api";
import { STAGES, TrackedApplication, stageOf } from "@/lib/applications";

// Application tracker (M6.4): the signed-in user's own rows from /api/v1/applications; nothing is made up.

const EMPTY = { university_name: "", program_name: "", deadline: "", notes: "" };

export default function ApplicationsPage() {
    const [signedIn, setSignedIn] = useState<boolean | null>(null);
    const [applications, setApplications] = useState<TrackedApplication[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState(EMPTY);
    const [saving, setSaving] = useState(false);

    const load = useCallback(async () => {
        try {
            setApplications(await api<TrackedApplication[]>("/api/v1/applications"));
            setError(null);
        } catch (e: any) {
            if (e?.status === 401) setSignedIn(false);
            else setError(e?.message ?? "Could not load your applications.");
        }
    }, []);

    useEffect(() => {
        const authed = isAuthenticated();
        setSignedIn(authed);
        if (authed) load();
    }, [load]);

    const add = async (event: FormEvent) => {
        event.preventDefault();
        setSaving(true);
        try {
            await api("/api/v1/applications", {
                method: "POST",
                json: {
                    university_name: form.university_name.trim(),
                    program_name: form.program_name.trim(),
                    deadline: form.deadline ? `${form.deadline}T00:00:00` : null,
                    notes: form.notes.trim() || null,
                },
            });
            setForm(EMPTY);
            setShowForm(false);
            await load();
        } catch (e: any) {
            setError(e?.message ?? "Could not save the application.");
        } finally {
            setSaving(false);
        }
    };

    const setStage = async (id: number, status: string) => {
        try {
            await api(`/api/v1/applications/${id}`, { method: "PATCH", json: { status } });
            await load();
        } catch (e: any) {
            setError(e?.message ?? "Could not update the application.");
        }
    };

    const remove = async (application: TrackedApplication) => {
        if (!window.confirm(`Remove ${application.university_name} (${application.program_name}) from your tracker?`)) return;
        try {
            await api(`/api/v1/applications/${application.id}`, { method: "DELETE" });
            await load();
        } catch (e: any) {
            setError(e?.message ?? "Could not remove the application.");
        }
    };

    const input = "w-full px-3 py-2 rounded-lg border border-slate-200 text-sm font-normal text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20";

    return (
        <div className="p-8 space-y-8 max-w-5xl mx-auto">
            <header className="flex justify-between items-center">
                <div className="space-y-1">
                    <h1 className="text-3xl font-bold tracking-tight">Application Tracker</h1>
                    <p className="text-slate-500 text-sm">The applications you add here, with their stage and deadline.</p>
                </div>
                {signedIn && (
                    <button
                        onClick={() => setShowForm((open) => !open)}
                        className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl shadow-lg shadow-primary/20 hover:bg-primary/90 transition-all font-bold text-sm"
                    >
                        <Plus className="h-4 w-4" /> New Application
                    </button>
                )}
            </header>

            {signedIn === false && (
                <div className="p-8 rounded-2xl border border-slate-100 bg-white text-center space-y-3">
                    <p className="text-sm text-slate-600">Sign in to track your applications.</p>
                    <Link href="/login?redirect=/applications" className="inline-block px-4 py-2 bg-primary text-white rounded-lg text-sm font-bold">
                        Sign In
                    </Link>
                </div>
            )}

            {error && (
                <div role="alert" className="p-4 rounded-xl border border-red-100 bg-red-50 text-sm text-red-700">{error}</div>
            )}

            {signedIn && showForm && (
                <form onSubmit={add} className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm grid grid-cols-1 md:grid-cols-2 gap-4">
                    <label className="space-y-1 text-xs font-bold text-slate-500">
                        University or school
                        <input required maxLength={200} className={input} value={form.university_name}
                            onChange={(e) => setForm({ ...form, university_name: e.target.value })} />
                    </label>
                    <label className="space-y-1 text-xs font-bold text-slate-500">
                        Program
                        <input required maxLength={200} className={input} value={form.program_name}
                            onChange={(e) => setForm({ ...form, program_name: e.target.value })} />
                    </label>
                    <label className="space-y-1 text-xs font-bold text-slate-500">
                        Deadline (optional)
                        <input type="date" className={input} value={form.deadline}
                            onChange={(e) => setForm({ ...form, deadline: e.target.value })} />
                    </label>
                    <label className="space-y-1 text-xs font-bold text-slate-500">
                        Notes (optional)
                        <input maxLength={2000} className={input} value={form.notes}
                            onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                    </label>
                    <div className="md:col-span-2 flex justify-end gap-3">
                        <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 text-sm text-slate-500">Cancel</button>
                        <button type="submit" disabled={saving} className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-bold disabled:opacity-50">
                            {saving ? "Saving..." : "Add"}
                        </button>
                    </div>
                </form>
            )}

            {signedIn && applications === null && !error && <p className="text-sm text-slate-400">Loading your applications...</p>}

            {signedIn && applications?.length === 0 && (
                <div className="p-8 rounded-2xl border border-dashed border-slate-200 bg-white text-center text-sm text-slate-500">
                    You haven&apos;t added any applications yet. Use &ldquo;New Application&rdquo; to add the first one.
                </div>
            )}

            <div className="space-y-4">
                {(applications ?? []).map((application) => {
                    const stage = stageOf(application.status);
                    return (
                        <div key={application.id} className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm flex flex-wrap items-center gap-6">
                            <div className={`p-4 rounded-xl ${stage.style}`}>
                                <ClipboardList className="h-6 w-6" />
                            </div>
                            <div className="flex-1 min-w-48 space-y-1">
                                <h3 className="text-lg font-bold">{application.university_name}</h3>
                                <p className="text-sm text-slate-500">{application.program_name}</p>
                                {application.notes && <p className="text-xs text-slate-400">{application.notes}</p>}
                            </div>
                            <div className="text-right space-y-1">
                                <p className="flex items-center gap-1 justify-end text-xs text-slate-500">
                                    <CalendarDays className="h-3 w-3" />
                                    {application.deadline ? `Deadline ${formatDate(application.deadline)}` : "No deadline set"}
                                </p>
                                <p className="text-[10px] text-slate-400">Updated {formatDate(application.updated_at)}</p>
                            </div>
                            <select
                                aria-label={`Stage of ${application.university_name}`}
                                value={application.status}
                                onChange={(e) => setStage(application.id, e.target.value)}
                                className={`px-3 py-2 rounded-lg text-xs font-bold border-0 ${stage.style}`}
                            >
                                {!STAGES.some((s) => s.value === application.status) && <option value={application.status}>{application.status}</option>}
                                {STAGES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                            </select>
                            <button onClick={() => remove(application)} aria-label={`Remove ${application.university_name}`}
                                className="p-2 text-slate-300 hover:text-red-500 transition-colors">
                                <Trash2 className="h-4 w-4" />
                            </button>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
