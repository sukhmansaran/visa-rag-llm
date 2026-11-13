"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Check, ClipboardCheck, ListTree, RefreshCw, X } from "lucide-react";
import { isAuthenticated, loadSession } from "@/lib/auth";
import { api, formatDate } from "@/lib/api";

// Admin page (M6.5, D8): the review queue for live-fetched pages (M5.5b) and a read-only view of request traces.
// The server decides who is an admin (403 otherwise); this page only shows what the admin API returns.

interface ReviewItem {
    id: number;
    source_name: string | null;
    url: string;
    title: string;
    chars: number;
    status: string;
    outcome: string | null;
    origin?: string;      // agent_fetch (an answer needed the page) | policy_watch (the daily check, M7)
    analysed?: boolean;
    fetched_at: string;
    reviewed_at: string | null;
}

// M7.2: what changed, worked out by code; the summary is the model's only when code found its numbers in the diff
interface ChangeAnalysis {
    lines_removed: number;
    lines_added: number;
    numbers_removed: string[];
    numbers_added: string[];
    rules: { key: string; value: string; sourced_from_this_page: boolean }[];
    chunks: number[];
    summary: string;
    summary_by: "model" | "code";
    kind: string;
    first_version: boolean;
}

interface ReviewDetail extends ReviewItem {
    analysis: ChangeAnalysis | null;
    text: string;
    stored_text: string;
    stored_scraped_at: string | null;
    diff: string[];
}

interface TraceSummary {
    trace_id: string;
    created_at: string;
    endpoint: string;
    status: string;
    source: string | null;
    latency_ms: number;
    llm_calls: number;
    error: string | null;
}

interface TraceDetail extends Omit<TraceSummary, "llm_calls"> {
    steps: Record<string, any>[];
    llm_calls: Record<string, any>[];
    query_redacted: string;
    answer_redacted: string;
    versions: Record<string, string | null>;
}

type Access = "checking" | "signed_out" | "forbidden" | "admin";

const STATUS_STYLE: Record<string, string> = {
    pending: "bg-amber-50 text-amber-700",
    approved: "bg-green-50 text-green-700",
    rejected: "bg-slate-100 text-slate-600",
    answered: "bg-green-50 text-green-700",
    refused: "bg-amber-50 text-amber-700",
    blocked: "bg-red-50 text-red-700",
    error: "bg-red-50 text-red-700",
};

function Badge({ status }: { status: string }) {
    return <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${STATUS_STYLE[status] ?? "bg-slate-100 text-slate-600"}`}>{status}</span>;
}

export default function AdminPage() {
    const [access, setAccess] = useState<Access>("checking");
    const [tab, setTab] = useState<"review" | "traces">("review");
    const [error, setError] = useState<string | null>(null);

    const fail = useCallback((e: any, fallback: string) => {
        if (e?.status === 401) setAccess("signed_out");
        else if (e?.status === 403) setAccess("forbidden");
        else setError(e?.message ?? fallback);
    }, []);

    useEffect(() => {
        if (!isAuthenticated()) {
            setAccess("signed_out");
            return;
        }
        loadSession().then((user) => setAccess(!user ? "signed_out" : user.is_admin ? "admin" : "forbidden"));
    }, []);

    if (access !== "admin") {
        return (
            <div className="p-8 max-w-3xl mx-auto">
                <div className="p-8 rounded-2xl border border-slate-100 bg-white text-center space-y-3 text-sm text-slate-600">
                    {access === "checking" && <p>Checking your access...</p>}
                    {access === "forbidden" && <p>This page is for administrators only.</p>}
                    {access === "signed_out" && (
                        <>
                            <p>Sign in with an administrator account to open this page.</p>
                            <Link href="/login?redirect=/admin" className="inline-block px-4 py-2 bg-primary text-white rounded-lg font-bold">Sign In</Link>
                        </>
                    )}
                </div>
            </div>
        );
    }

    const tabStyle = (name: string) =>
        `flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold ${tab === name ? "bg-slate-900 text-white" : "bg-white text-slate-500 border border-slate-100"}`;

    return (
        <div className="p-8 space-y-6 max-w-7xl mx-auto">
            <header className="space-y-1">
                <h1 className="text-3xl font-bold tracking-tight">Administration</h1>
                <p className="text-slate-500 text-sm">Review pages the agent fetched before they enter the knowledge base, and inspect how requests were answered.</p>
            </header>
            <div className="flex gap-3">
                <button className={tabStyle("review")} onClick={() => { setTab("review"); setError(null); }}><ClipboardCheck className="h-4 w-4" /> Review queue</button>
                <button className={tabStyle("traces")} onClick={() => { setTab("traces"); setError(null); }}><ListTree className="h-4 w-4" /> Request traces</button>
            </div>
            {error && <div role="alert" className="p-4 rounded-xl border border-red-100 bg-red-50 text-sm text-red-700">{error}</div>}
            {tab === "review" ? <ReviewQueue fail={fail} clearError={() => setError(null)} /> : <Traces fail={fail} />}
        </div>
    );
}

function ReviewQueue({ fail, clearError }: { fail: (e: any, fallback: string) => void; clearError: () => void }) {
    const [status, setStatus] = useState("pending");
    const [items, setItems] = useState<ReviewItem[] | null>(null);
    const [open, setOpen] = useState<ReviewDetail | null>(null);
    const [view, setView] = useState<"diff" | "side">("diff");
    const [busy, setBusy] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            setItems((await api<{ items: ReviewItem[] }>(`/api/v1/admin/review-queue?status=${status}`)).items);
        } catch (e) {
            fail(e, "Could not load the review queue.");
        }
    }, [status, fail]);

    useEffect(() => {
        setItems(null);
        load();
    }, [load]);

    const show = async (id: number) => {
        clearError();
        setNotice(null);
        try {
            setOpen(await api<ReviewDetail>(`/api/v1/admin/review-queue/${id}`));
        } catch (e) {
            fail(e, "Could not load the item.");
        }
    };

    const decide = async (action: "approve" | "reject") => {
        if (!open) return;
        const question = action === "approve"
            ? "Approve this page? The database and knowledge base are backed up first, then this exact text replaces the stored copy. This can take a minute."
            : "Reject this page? Its fetched text is deleted; the knowledge base is not changed.";
        if (!window.confirm(question)) return;
        setBusy(action);
        clearError();
        try {
            const result = await api<ReviewItem>(`/api/v1/admin/review-queue/${open.id}/${action}`, { method: "POST" });
            setNotice(`${action === "approve" ? "Approved" : "Rejected"}: ${result.outcome ?? result.status}`);
            setOpen(null);
            await load();
        } catch (e) {
            fail(e, `Could not ${action} the item.`);
        } finally {
            setBusy(null);
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-3">
                <select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setOpen(null); }}
                    className="px-3 py-2 rounded-lg border border-slate-200 text-sm bg-white">
                    <option value="pending">Waiting for review</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                    <option value="all">All</option>
                </select>
                <button onClick={load} className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm text-slate-600">
                    <RefreshCw className="h-3 w-3" /> Refresh
                </button>
            </div>
            {notice && <div role="status" className="p-4 rounded-xl border border-green-100 bg-green-50 text-sm text-green-700">{notice}</div>}
            {items === null && <p className="text-sm text-slate-400">Loading...</p>}
            {items?.length === 0 && (
                <p className="p-6 rounded-xl border border-dashed border-slate-200 bg-white text-sm text-slate-500">
                    {status === "pending" ? "Nothing is waiting for review. A page appears here when the agent fetches an official page whose text differs from the stored copy." : "No items."}
                </p>
            )}
            <div className="space-y-2">
                {(items ?? []).map((item) => (
                    <button key={item.id} onClick={() => show(item.id)}
                        className={`w-full text-left p-4 rounded-xl border bg-white flex flex-wrap items-center gap-4 hover:border-primary/30 ${open?.id === item.id ? "border-primary/50" : "border-slate-100"}`}>
                        <Badge status={item.status} />
                        <div className="flex-1 min-w-64">
                            <p className="text-sm font-bold">{item.source_name ?? item.title}</p>
                            <p className="text-xs text-slate-500 break-all">{item.url}</p>
                            {item.outcome && <p className="text-xs text-slate-400">{item.outcome}</p>}
                            <p className="text-[10px] text-slate-400 uppercase font-bold">
                                {item.origin === "policy_watch" ? "Found by the daily page check" : "Fetched for an answer"}
                                {item.status === "pending" && !item.analysed ? " · not analysed yet" : ""}
                            </p>
                        </div>
                        <p className="text-xs text-slate-500 text-right">Fetched {formatDate(item.fetched_at)}<br />{item.chars.toLocaleString()} characters</p>
                    </button>
                ))}
            </div>

            {open && (
                <section className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm space-y-4">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="space-y-1">
                            <h2 className="text-lg font-bold">{open.source_name ?? open.title}</h2>
                            <a href={open.url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline break-all">{open.url}</a>
                            <p className="text-xs text-slate-500">
                                Fetched {formatDate(open.fetched_at)}. Stored copy: {open.stored_scraped_at ? formatDate(open.stored_scraped_at) : "none yet"}.
                            </p>
                        </div>
                        {open.status === "pending" && (
                            <div className="flex gap-2">
                                <button onClick={() => decide("reject")} disabled={busy !== null}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-200 text-sm font-bold text-slate-600 disabled:opacity-50">
                                    <X className="h-4 w-4" /> {busy === "reject" ? "Rejecting..." : "Reject"}
                                </button>
                                <button onClick={() => decide("approve")} disabled={busy !== null}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-bold disabled:opacity-50">
                                    <Check className="h-4 w-4" /> {busy === "approve" ? "Backing up and storing..." : "Approve"}
                                </button>
                            </div>
                        )}
                    </div>

                    {open.analysis && <AnalysisPanel analysis={open.analysis} />}

                    {open.status !== "pending" ? (
                        <p className="text-sm text-slate-500">This item was {open.status}{open.reviewed_at ? ` on ${formatDate(open.reviewed_at)}` : ""}; its fetched text is no longer kept here.</p>
                    ) : (
                        <>
                            <div className="flex gap-2 text-xs font-bold">
                                <button onClick={() => setView("diff")} className={`px-3 py-1 rounded ${view === "diff" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>What changed</button>
                                <button onClick={() => setView("side")} className={`px-3 py-1 rounded ${view === "side" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>Side by side</button>
                            </div>
                            {view === "diff" ? (
                                <pre className="max-h-[32rem] overflow-auto rounded-lg border border-slate-100 bg-slate-50 p-4 text-xs leading-relaxed whitespace-pre-wrap">
                                    {open.diff.length === 0 && <span className="text-slate-500">No stored copy to compare with, or the texts are identical.</span>}
                                    {open.diff.map((line, i) => (
                                        <span key={i} className={`block ${line.startsWith("+") ? "bg-green-100 text-green-900" : line.startsWith("-") ? "bg-red-100 text-red-900" : line.startsWith("@@") ? "text-slate-400" : "text-slate-600"}`}>
                                            {line || " "}
                                        </span>
                                    ))}
                                </pre>
                            ) : (
                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                                    <div className="space-y-1">
                                        <p className="text-xs font-bold text-slate-500">Stored copy (what answers use now)</p>
                                        <pre className="max-h-[32rem] overflow-auto rounded-lg border border-slate-100 bg-slate-50 p-4 text-xs whitespace-pre-wrap">{open.stored_text || "None yet."}</pre>
                                    </div>
                                    <div className="space-y-1">
                                        <p className="text-xs font-bold text-slate-500">Fetched page (what approving would store)</p>
                                        <pre className="max-h-[32rem] overflow-auto rounded-lg border border-slate-100 bg-slate-50 p-4 text-xs whitespace-pre-wrap">{open.text}</pre>
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </section>
            )}
        </div>
    );
}

function AnalysisPanel({ analysis }: { analysis: ChangeAnalysis }) {
    return (
        <div className="rounded-xl border border-blue-100 bg-blue-50 p-4 space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-bold uppercase text-blue-900">What changed</span>
                <span className="px-2 py-0.5 rounded bg-white text-[10px] font-bold uppercase text-blue-700">{analysis.kind}</span>
                <span className="text-[10px] text-blue-700">
                    {analysis.summary_by === "model" ? "Summary by the model; its numbers were checked against the diff" : "Summary by code"}
                </span>
            </div>
            <p className="text-slate-800">{analysis.summary}</p>
            {analysis.first_version && <p className="text-xs text-slate-600">There is no stored copy of this page yet; approving would add it.</p>}
            <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-slate-700">
                <div>
                    <dt className="font-bold">Figures no longer on the page</dt>
                    <dd>{analysis.numbers_removed.join(", ") || "None"}</dd>
                </div>
                <div>
                    <dt className="font-bold">New figures</dt>
                    <dd>{analysis.numbers_added.join(", ") || "None"}</dd>
                </div>
                <div className="md:col-span-2">
                    <dt className="font-bold">Rules to check in ircc_rules.yaml</dt>
                    <dd>
                        {analysis.rules.length === 0 ? "None of the rule figures left this page." : (
                            <ul className="list-disc pl-5 space-y-0.5">
                                {analysis.rules.map((rule) => (
                                    <li key={rule.key}>
                                        <code>{rule.key}</code> = {rule.value}
                                        {!rule.sourced_from_this_page && " (the rule cites another page)"}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </dd>
                </div>
                <div className="md:col-span-2">
                    <dt className="font-bold">Stored passages that contain removed text</dt>
                    <dd>{analysis.chunks.length ? `${analysis.chunks.length} (passage numbers ${analysis.chunks.join(", ")})` : "None"}</dd>
                </div>
            </dl>
            <p className="text-[11px] text-slate-500">
                Approving replaces the stored copy of the page. It never edits the rules file: update a listed rule yourself if the page confirms a new figure.
            </p>
        </div>
    );
}

function Traces({ fail }: { fail: (e: any, fallback: string) => void }) {
    const [status, setStatus] = useState("");
    const [traces, setTraces] = useState<TraceSummary[] | null>(null);
    const [open, setOpen] = useState<TraceDetail | null>(null);

    const load = useCallback(async () => {
        try {
            const query = status ? `&status=${status}` : "";
            setTraces((await api<{ traces: TraceSummary[] }>(`/api/v1/admin/traces?limit=50${query}`)).traces);
        } catch (e) {
            fail(e, "Could not load the traces.");
        }
    }, [status, fail]);

    useEffect(() => {
        setTraces(null);
        load();
    }, [load]);

    const show = async (id: string) => {
        try {
            setOpen(await api<TraceDetail>(`/api/v1/admin/traces/${encodeURIComponent(id)}`));
        } catch (e) {
            fail(e, "Could not load the trace.");
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-3">
                <select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setOpen(null); }}
                    className="px-3 py-2 rounded-lg border border-slate-200 text-sm bg-white">
                    <option value="">All requests</option>
                    <option value="answered">Answered</option>
                    <option value="refused">Refused</option>
                    <option value="blocked">Blocked</option>
                    <option value="error">Errors</option>
                </select>
                <button onClick={load} className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm text-slate-600">
                    <RefreshCw className="h-3 w-3" /> Refresh
                </button>
                <p className="text-xs text-slate-400">The 50 most recent. Questions and answers are stored with personal details removed.</p>
            </div>
            {traces === null && <p className="text-sm text-slate-400">Loading...</p>}
            {traces?.length === 0 && <p className="p-6 rounded-xl border border-dashed border-slate-200 bg-white text-sm text-slate-500">No traces.</p>}
            <div className="space-y-2">
                {(traces ?? []).map((trace) => (
                    <button key={trace.trace_id} onClick={() => show(trace.trace_id)}
                        className={`w-full text-left p-3 rounded-xl border bg-white flex flex-wrap items-center gap-4 hover:border-primary/30 ${open?.trace_id === trace.trace_id ? "border-primary/50" : "border-slate-100"}`}>
                        <Badge status={trace.status} />
                        <span className="text-xs text-slate-600 flex-1 min-w-48">{new Date(trace.created_at + "Z").toLocaleString()} · {trace.endpoint}{trace.source ? ` · ${trace.source}` : ""}</span>
                        <span className="text-xs text-slate-500">{(trace.latency_ms / 1000).toFixed(1)} s · {trace.llm_calls} model calls</span>
                        {trace.error && <span className="text-xs text-red-600 w-full">{trace.error}</span>}
                    </button>
                ))}
            </div>

            {open && (
                <section className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm space-y-4 text-sm">
                    <div className="flex items-center gap-3">
                        <Badge status={open.status} />
                        <span className="text-xs text-slate-500">{open.trace_id} · {(open.latency_ms / 1000).toFixed(1)} s</span>
                    </div>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        <div className="space-y-1">
                            <p className="text-xs font-bold text-slate-500">Question (redacted)</p>
                            <pre className="max-h-48 overflow-auto rounded-lg bg-slate-50 p-3 text-xs whitespace-pre-wrap">{open.query_redacted || "(empty)"}</pre>
                        </div>
                        <div className="space-y-1">
                            <p className="text-xs font-bold text-slate-500">Answer (redacted)</p>
                            <pre className="max-h-48 overflow-auto rounded-lg bg-slate-50 p-3 text-xs whitespace-pre-wrap">{open.answer_redacted || "(empty)"}</pre>
                        </div>
                    </div>
                    <div className="space-y-1">
                        <p className="text-xs font-bold text-slate-500">Steps ({open.steps.length})</p>
                        <ol className="rounded-lg border border-slate-100 divide-y divide-slate-100">
                            {open.steps.map((step, i) => {
                                const { name, ms, ...rest } = step;
                                return (
                                    <li key={i} className="px-3 py-2 text-xs flex flex-wrap gap-3">
                                        <span className="font-bold w-40">{i + 1}. {String(name)}</span>
                                        <span className="text-slate-400 w-16">{typeof ms === "number" ? `${ms} ms` : ""}</span>
                                        <span className="text-slate-600 flex-1 break-all">{Object.keys(rest).length ? JSON.stringify(rest) : ""}</span>
                                    </li>
                                );
                            })}
                        </ol>
                    </div>
                    <div className="space-y-1">
                        <p className="text-xs font-bold text-slate-500">Model calls ({open.llm_calls.length}) and versions</p>
                        <pre className="max-h-64 overflow-auto rounded-lg bg-slate-50 p-3 text-xs whitespace-pre-wrap">{JSON.stringify({ versions: open.versions, llm_calls: open.llm_calls }, null, 2)}</pre>
                    </div>
                </section>
            )}
        </div>
    );
}
