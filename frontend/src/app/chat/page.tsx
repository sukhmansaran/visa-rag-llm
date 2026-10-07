"use client";

import { useState, useEffect, useRef } from "react";
import { Send, BookOpen, ChevronDown, ChevronUp, Database, Zap, Clock, ExternalLink, ShieldCheck, FileText } from "lucide-react";
import Link from "next/link";
import { MarkdownMessage } from "@/components/MarkdownMessage";


interface Message {
    role: "user" | "assistant";
    content: string;
    metrics?: Record<string, any>;
    sources?: any[];
    streaming?: boolean;
    guardrail_blocked?: boolean;
}

export default function ChatPage() {
    const [query, setQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [showDebug, setShowDebug] = useState(false);
    const [messages, setMessages] = useState<Message[]>([]);
    const [profile, setProfile] = useState<any>(null);
    const [sessionId, setSessionId] = useState<string | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const abortControllerRef = useRef<AbortController | null>(null);

    useEffect(() => {
        const data = localStorage.getItem("user_profile");
        if (data) setProfile(JSON.parse(data));
    }, []);

    // Auto-scroll to bottom when messages update
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    const handleSend = async (e?: React.FormEvent, overrideText?: string) => {
        if (e) e.preventDefault();
        const textToSend = (overrideText !== undefined ? overrideText : query).trim();
        if (!textToSend || loading) return;

        const userMessage: Message = { role: "user", content: textToSend };
        setMessages(prev => [...prev, userMessage]);
        setQuery("");
        setLoading(true);

        // Add an empty assistant message that we'll stream into
        setMessages(prev => [...prev, {
            role: "assistant",
            content: "",
            streaming: true,
        }]);

        // Cancel any previous request
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
        abortControllerRef.current = new AbortController();

        try {
            // Extract prior dialogue turns (up to 6) for conversational continuity
            const historyPayload = messages
                .filter(m => m.content && !m.streaming)
                .slice(-6)
                .map(m => ({
                    role: m.role,
                    content: m.content,
                }));

            console.log("[CHAT] Sending request to backend with history:", historyPayload.length, "turns for:", textToSend);
            const response = await fetch("http://localhost:8000/api/v1/chat/answer/stream", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    query: textToSend,
                    country: profile?.country || "Canada",
                    university: profile?.university || null,
                    sessionId: sessionId,
                    chat_history: historyPayload,
                }),
                signal: abortControllerRef.current.signal,
            });

            if (!response.ok) {
                throw new Error(`Server returned HTTP ${response.status} (${response.statusText})`);
            }

            if (!response.body) {
                throw new Error("No response stream body returned by server");
            }

            // Read the SSE stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() ?? "";

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const jsonStr = line.slice(6).trim();
                    if (!jsonStr) continue;

                    try {
                        const event = JSON.parse(jsonStr);

                        if (event.type === "session") {
                            setSessionId(event.session_id);
                        } else if (event.type === "guardrail_blocked") {
                            setMessages(prev => {
                                const updated = [...prev];
                                const last = updated[updated.length - 1];
                                if (last?.role === "assistant") {
                                    updated[updated.length - 1] = {
                                        ...last,
                                        guardrail_blocked: true,
                                    };
                                }
                                return updated;
                            });
                        } else if (event.type === "chunk") {
                            // Append chunk to the streaming message
                            setMessages(prev => {
                                const updated = [...prev];
                                const last = updated[updated.length - 1];
                                if (last?.role === "assistant") {
                                    updated[updated.length - 1] = {
                                        ...last,
                                        content: last.content + event.content,
                                        streaming: true,
                                    };
                                }
                                return updated;
                            });
                        } else if (event.type === "done") {
                            // Mark streaming complete with full metadata
                            setMessages(prev => {
                                const updated = [...prev];
                                const last = updated[updated.length - 1];
                                if (last?.role === "assistant") {
                                    updated[updated.length - 1] = {
                                        ...last,
                                        content: event.full_response || last.content,
                                        sources: event.sources || [],
                                        metrics: event.metrics || {},
                                        streaming: false,
                                    };
                                }
                                return updated;
                            });
                        } else if (event.type === "error") {
                            setMessages(prev => {
                                const updated = [...prev];
                                const last = updated[updated.length - 1];
                                if (last?.role === "assistant") {
                                    updated[updated.length - 1] = {
                                        ...last,
                                        content: `Server Error: ${event.message}`,
                                        streaming: false,
                                    };
                                }
                                return updated;
                            });
                        }
                    } catch {
                        // Skip malformed JSON lines
                    }
                }
            }
        } catch (error: any) {
            console.error("[CHAT] Request failed:", error);
            if (error.name === "AbortError") return;

            setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant") {
                    updated[updated.length - 1] = {
                        ...last,
                        content: `⚠️ Could not reach backend: ${error.message || "Failed to fetch"}. Please ensure the backend is running at http://localhost:8000.`,
                        streaming: false,
                    };
                }
                return updated;
            });
        } finally {
            setLoading(false);
        }
    };

    const handleQuickQuestion = (q: string) => {
        setQuery(q);
        handleSend(undefined, q);
    };

    return (
        <div className="max-w-4xl mx-auto py-12 px-4 h-screen flex flex-col">
            <div className="flex justify-between items-center mb-8 shrink-0">
                <h2 className="text-2xl font-bold flex items-center gap-2">
                    <BookOpen className="h-6 w-6 text-primary" /> Verified Visa Assistant
                </h2>
                <Link href="/demo/metrics" className="text-xs text-slate-500 hover:underline">
                    System Metrics
                </Link>
            </div>

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
                    <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
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
                            onClick={() => {
                                if (abortControllerRef.current) abortControllerRef.current.abort();
                                setLoading(false);
                            }}
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
