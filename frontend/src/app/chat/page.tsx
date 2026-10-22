"use client";

import { useState, useEffect, useRef } from "react";
import { Send, BookOpen, ChevronDown, ChevronUp, Database, Zap, Clock, ExternalLink, ShieldCheck, FileText, Lock } from "lucide-react";
import Link from "next/link";
import { MarkdownMessage } from "@/components/MarkdownMessage";
import { isAuthenticated } from "@/lib/auth";
import { cancelJob, describeStep, followJob, JobEvent, JobRequestError, startAnswerJob } from "@/lib/jobStream";


interface Message {
    role: "user" | "assistant";
    content: string;
    metrics?: Record<string, any>;
    sources?: any[];
    streaming?: boolean;
    guardrail_blocked?: boolean;
    progress?: string;          // current step label while the answer job runs
    steps?: number[];           // step numbers received (diagnostic jobs), for end-to-end checks
    status?: "running" | "done" | "error" | "cancelled";
}

const JOB_PARAM = "job";

function setJobInUrl(jobId: string | null) {
    const url = new URL(window.location.href);
    if (jobId) url.searchParams.set(JOB_PARAM, jobId);
    else url.searchParams.delete(JOB_PARAM);
    window.history.replaceState(null, "", url.pathname + url.search);
}

function errorText(reason: string | undefined): string {
    if (reason === "time_budget") return "\n\n⚠️ The answer took longer than the 5-minute limit and was stopped.";
    if (reason === "not_started") return "\n\n⚠️ The answer service isn't running right now. Please try again in a few minutes.";
    return "\n\n⚠️ The answer could not be completed. Please try again.";
}

export default function ChatPage() {
    const [query, setQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [showDebug, setShowDebug] = useState(false);
    const [messages, setMessages] = useState<Message[]>([]);
    const [profile, setProfile] = useState<any>(null);
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [isAuth, setIsAuth] = useState(true);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const abortControllerRef = useRef<AbortController | null>(null);

    useEffect(() => {
        setIsAuth(isAuthenticated());
        const data = localStorage.getItem("user_profile");
        if (data) setProfile(JSON.parse(data));
    }, []);

    // Auto-scroll to bottom when messages update
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    const jobIdRef = useRef<string | null>(null);
    const [connection, setConnection] = useState<"connected" | "reconnecting">("connected");

    const updateLastAssistant = (update: (message: Message) => Message) => {
        setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant") updated[updated.length - 1] = update(last);
            return updated;
        });
    };

    const handleJobEvent = (event: JobEvent) => {
        const data = event.data || {};
        switch (event.type) {
            case "step":
                updateLastAssistant(m => ({
                    ...m,
                    progress: describeStep(data),
                    steps: typeof data.n === "number" ? [...(m.steps || []), data.n] : m.steps,
                }));
                break;
            case "status":
                if (data.status === "waiting") updateLastAssistant(m => ({ ...m, progress: "Waiting for the answer service" }));
                break;
            case "chunk":
                updateLastAssistant(m => ({ ...m, content: m.content + (data.content || ""), streaming: true }));
                break;
            case "guardrail_blocked":
                // The English-only reply (M1.3) is a polite notice, not a blocked request: no firewall badge
                if (data.violation !== "UNSUPPORTED_LANGUAGE") updateLastAssistant(m => ({ ...m, guardrail_blocked: true }));
                break;
            case "done":
                updateLastAssistant(m => ({
                    ...m,
                    content: data.full_response || m.content,
                    sources: data.sources || [],
                    metrics: data.metrics || {},
                    streaming: false,
                    progress: undefined,
                    status: "done",
                }));
                break;
            case "error":
                updateLastAssistant(m => ({
                    ...m,
                    content: (data.partial || m.content) + errorText(data.reason),
                    streaming: false,
                    progress: undefined,
                    status: "error",
                }));
                break;
            case "cancelled":
                updateLastAssistant(m => ({
                    ...m,
                    content: (data.partial || m.content) || "Stopped.",
                    streaming: false,
                    progress: undefined,
                    status: "cancelled",
                }));
                break;
        }
    };

    /** Follow a job until it ends; reconnects automatically. Used for new questions and after a reload. */
    const runJob = async (jobId: string) => {
        abortControllerRef.current?.abort();
        const controller = new AbortController();
        abortControllerRef.current = controller;
        jobIdRef.current = jobId;
        setLoading(true);
        try {
            await followJob(jobId, handleJobEvent, { signal: controller.signal, onConnection: setConnection });
        } catch (error: any) {
            if (error?.name === "AbortError") return;
            const message = error instanceof JobRequestError && (error.status === 401 || error.status === 403)
                ? "Your session has expired. Please [sign in again](/login?redirect=/chat)."
                : `⚠️ ${error?.message || "The answer could not be loaded."}`;
            updateLastAssistant(m => ({ ...m, content: message, streaming: false, progress: undefined, status: "error" }));
        } finally {
            if (jobIdRef.current === jobId) {
                jobIdRef.current = null;
                setLoading(false);
                setConnection("connected");
                setJobInUrl(null);
            }
        }
    };

    // After a reload, re-attach to the answer that was running (its id is kept in the URL)
    useEffect(() => {
        const jobId = new URL(window.location.href).searchParams.get(JOB_PARAM);
        if (!jobId || !isAuthenticated()) return;
        setMessages(prev => [...prev, { role: "assistant", content: "", streaming: true, status: "running" }]);
        runJob(jobId);
        return () => abortControllerRef.current?.abort();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleStop = async () => {
        const jobId = jobIdRef.current;
        if (jobId) {
            await cancelJob(jobId); // the job stops on the server; the "cancelled" event ends the stream
            updateLastAssistant(m => ({ ...m, progress: "Stopping…" }));
        } else {
            abortControllerRef.current?.abort();
            setLoading(false);
        }
    };

    const handleSend = async (e?: React.FormEvent, overrideText?: string) => {
        if (e) e.preventDefault();
        const textToSend = (overrideText !== undefined ? overrideText : query).trim();
        if (!textToSend || loading) return;

        setMessages(prev => [...prev, { role: "user", content: textToSend }]);
        setQuery("");

        // Conversation history is loaded server-side from the session (sessionId); never sent by the client
        if (!isAuthenticated()) {
            setMessages(prev => [...prev, {
                role: "assistant",
                content: "Authentication is required to query official records. Please [sign in](/login?redirect=/chat) or [create a free account](/signup?redirect=/chat).",
                streaming: false,
            }]);
            return;
        }

        setMessages(prev => [...prev, { role: "assistant", content: "", streaming: true, status: "running", progress: "Starting" }]);
        setLoading(true);
        try {
            const job = await startAnswerJob({
                query: textToSend,
                country: profile?.country || "Canada",
                university: profile?.university || null,
                sessionId: sessionId,
            });
            setSessionId(job.session_id);
            setJobInUrl(job.job_id);
            await runJob(job.job_id);
        } catch (error: any) {
            const message = error instanceof JobRequestError && (error.status === 401 || error.status === 403)
                ? "Your session has expired. Please [sign in again](/login?redirect=/chat)."
                : `⚠️ Could not start the answer: ${error?.message || "Failed to fetch"}.`;
            updateLastAssistant(m => ({ ...m, content: message, streaming: false, progress: undefined, status: "error" }));
            setLoading(false);
        }
    };

    const handleQuickQuestion = (q: string) => {
        setQuery(q);
        handleSend(undefined, q);
    };

    return (
        <div className="max-w-4xl mx-auto py-12 px-4 h-screen flex flex-col">
            <div className="flex justify-between items-center mb-6 shrink-0">
                <h2 className="text-2xl font-bold flex items-center gap-2">
                    <BookOpen className="h-6 w-6 text-primary" /> Verified Visa Assistant
                </h2>
                <div className="flex items-center gap-3">
                    {!isAuth && (
                        <Link href="/login?redirect=/chat" className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-500 font-medium">
                            Sign In
                        </Link>
                    )}
                    <Link href="/demo/metrics" className="text-xs text-slate-500 hover:underline">
                        System Metrics
                    </Link>
                </div>
            </div>

            {!isAuth && (
                <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-blue-500/30 bg-blue-950/30 px-4 py-3 text-xs text-blue-300">
                    <div className="flex items-center gap-2">
                        <Lock className="h-4 w-4 shrink-0" />
                        <span>Sign in required for full access to verified IRCC chat.</span>
                    </div>
                    <div className="flex items-center gap-2 font-medium">
                        <Link href="/login?redirect=/chat" className="hover:underline">Login</Link>
                        <span>·</span>
                        <Link href="/signup?redirect=/chat" className="hover:underline">Sign Up</Link>
                    </div>
                </div>
            )}

            {/* Chat Area */}
            <div className="flex-1 overflow-y-auto space-y-6 pb-28 px-2">
                {messages.length === 0 && (
                    <div className="text-center py-20 bg-slate-50 dark:bg-slate-900 rounded-3xl border-2 border-dashed border-slate-200 dark:border-slate-800">
                        <p className="text-slate-500">
                            How can I help with your {profile?.country || "Canada"} visa application?
                        </p>
                        <div className="mt-4 flex flex-wrap justify-center gap-2">
                            <button
                                onClick={() => handleQuickQuestion("What are the financial requirements for a Canada student visa?")}
                                className="text-xs px-3 py-1 bg-white dark:bg-slate-800 rounded-full border border-slate-200 dark:border-slate-700 hover:border-primary transition-colors"
                            >
                                Financial Requirements
                            </button>
                            <button
                                onClick={() => handleQuickQuestion("What documents do I need for the SDS program?")}
                                className="text-xs px-3 py-1 bg-white dark:bg-slate-800 rounded-full border border-slate-200 dark:border-slate-700 hover:border-primary transition-colors"
                            >
                                SDS Checklist
                            </button>
                            <button
                                onClick={() => handleQuickQuestion("How long does Canada student visa processing take?")}
                                className="text-xs px-3 py-1 bg-white dark:bg-slate-800 rounded-full border border-slate-200 dark:border-slate-700 hover:border-primary transition-colors"
                            >
                                Processing Time
                            </button>
                        </div>
                    </div>
                )}

                {messages.map((msg, i) => (
                    <div
                        key={i}
                        className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                        data-testid={msg.role === "assistant" ? "assistant-message" : "user-message"}
                        data-status={msg.status}
                        data-steps={msg.steps?.join(",")}
                    >
                        <div className={`max-w-[85%] rounded-2xl p-4 ${msg.role === "user"
                                ? "bg-primary text-white rounded-br-none"
                                : "bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-bl-none shadow-sm"
                            }`}>
                            {msg.guardrail_blocked && (
                                <div className="mb-2.5 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                                    <ShieldCheck className="h-3.5 w-3.5" />
                                    <span>🛡️ Guardrail Firewall Intercepted</span>
                                </div>
                            )}

                            {msg.role === "assistant" && msg.streaming && msg.progress && (
                                <div data-testid="job-progress" className="mb-2 flex items-center gap-2 text-xs text-slate-500">
                                    <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                                    <span>{msg.progress}…</span>
                                    {connection === "reconnecting" && i === messages.length - 1 && (
                                        <span data-testid="reconnecting" className="rounded-full bg-amber-500/10 px-2 py-0.5 text-amber-600">
                                            Reconnecting
                                        </span>
                                    )}
                                </div>
                            )}

                            {msg.role === "assistant" ? (
                                <MarkdownMessage content={msg.content} isStreaming={msg.streaming} />
                            ) : (
                                <div className="whitespace-pre-wrap text-sm leading-relaxed">
                                    {msg.content}
                                </div>
                            )}


                            {/* Verified Source Citations */}
                            {msg.role === "assistant" && !msg.streaming && msg.sources && msg.sources.length > 0 && (
                                <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800 space-y-1.5">
                                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1">
                                        <BookOpen className="h-3 w-3" />
                                        Verified Official Sources
                                    </p>
                                    <div className="flex flex-wrap gap-2">
                                        {msg.sources.map((src: any, idx: number) => (
                                            <a
                                                key={idx}
                                                href={src.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-slate-50 dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg text-xs font-medium text-blue-600 dark:text-blue-400 border border-slate-200 dark:border-slate-700 transition-colors"
                                            >
                                                <ExternalLink className="h-3 w-3" />
                                                <span>{src.title || "Official IRCC Document"}</span>
                                            </a>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Telemetry Trace */}
                            {msg.role === "assistant" && !msg.streaming && msg.metrics && (
                                <div className="mt-4 pt-3 border-t border-slate-50 dark:border-slate-800">
                                    <button
                                        onClick={() => setShowDebug(!showDebug)}
                                        className="text-[10px] uppercase tracking-widest font-bold text-slate-400 flex items-center gap-1 hover:text-primary transition-colors"
                                    >
                                        <Database className="h-3 w-3" />
                                        {showDebug ? "Hide Trace" : "Show Trace"}
                                        {showDebug ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                                    </button>
                                    {showDebug && (
                                        <div className="mt-2 p-3 bg-slate-50 dark:bg-slate-950 rounded-lg space-y-2">
                                            <div className="grid grid-cols-2 gap-2">
                                                <TraceItem icon={<Zap className="h-3 w-3" />} label="Source" value={msg.metrics.source || "ollama"} />
                                                <TraceItem icon={<Clock className="h-3 w-3" />} label="Latency" value={msg.metrics.latency_ms ? `${msg.metrics.latency_ms}ms` : "—"} />
                                                <TraceItem icon={<ShieldCheck className="h-3 w-3" />} label="Confidence" value={msg.metrics.confidence_level ? `${msg.metrics.confidence_level} (${Math.round((msg.metrics.confidence || 0) * 100)}%)` : "—"} />
                                                <TraceItem 
                                                    icon={<FileText className="h-3 w-3" />} 
                                                    label="Evidence" 
                                                    value={
                                                        msg.metrics.retrieval_chunks && msg.metrics.retrieval_chunks > 0 
                                                            ? `${msg.metrics.retrieval_chunks} vector chunks` 
                                                            : (msg.sources && msg.sources.length > 0 ? `${msg.sources.length} Verified Doc` : "0")
                                                    } 
                                                />
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                ))}

                {loading && messages[messages.length - 1]?.content === "" && (
                    <div className="flex justify-start">
                        <div className="bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-2xl rounded-bl-none shadow-sm p-4">
                            <div className="flex gap-1 items-center h-4">
                                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                            </div>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <form onSubmit={handleSend} className="fixed bottom-8 left-0 right-0 max-w-4xl mx-auto px-4 z-50 pointer-events-auto">
                <div className="relative">
                    <input
                        type="text"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                handleSend();
                            }
                        }}
                        disabled={loading}
                        placeholder="Ask about funds, documents, or timelines..."
                        className="w-full h-14 pl-6 pr-14 rounded-full border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xl focus:outline-none focus:ring-2 focus:ring-primary/40 dark:shadow-none"
                    />
                    {loading ? (
                        <button
                            type="button"
                            onClick={handleStop}
                            data-testid="stop-button"
                            title="Cancel / Stop"
                            className="absolute right-2 top-2 h-10 w-10 flex items-center justify-center rounded-full bg-slate-700 text-white hover:bg-slate-800 transition-transform active:scale-95 cursor-pointer"
                        >
                            <span className="w-3 h-3 bg-white rounded-xs" />
                        </button>
                    ) : (
                        <button
                            type="submit"
                            disabled={!query.trim()}
                            onClick={(e) => {
                                e.preventDefault();
                                handleSend();
                            }}
                            title="Send message"
                            className="absolute right-2 top-2 h-10 w-10 flex items-center justify-center rounded-full bg-primary text-white disabled:opacity-40 transition-transform active:scale-95 cursor-pointer disabled:cursor-not-allowed shadow-md"
                        >
                            <Send className="h-4 w-4" />
                        </button>
                    )}
                </div>
            </form>
        </div>
    );
}

function TraceItem({ icon, label, value }: { icon: any; label: string; value: string }) {
    return (
        <div className="flex items-center gap-2">
            <div className="text-slate-400">{icon}</div>
            <div className="flex flex-col">
                <span className="text-[8px] uppercase text-slate-400 font-bold">{label}</span>
                <span className="text-[10px] font-mono text-slate-600 dark:text-slate-300 uppercase">{value}</span>
            </div>
        </div>
    );
}
