"use client";

import { useState, useEffect, useRef } from "react";
import { Send, BookOpen, ChevronDown, ChevronUp, Database, Zap, Clock } from "lucide-react";
import Link from "next/link";

interface Message {
    role: "user" | "assistant";
    content: string;
    metrics?: Record<string, any>;
    sources?: string[];
    streaming?: boolean;
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

    const handleSend = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!query.trim() || loading) return;

        const userMessage: Message = { role: "user", content: query };
        setMessages(prev => [...prev, userMessage]);
        const currentQuery = query;
        setQuery("");
        setLoading(true);

        // Add an empty assistant message that we'll stream into
        const assistantIndex = messages.length + 1;
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
            const response = await fetch("http://localhost:8000/api/v1/chat/answer/stream", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    query: currentQuery,
                    country: profile?.country || "Canada",
                    university: profile?.university || null,
                    sessionId: sessionId,
                }),
                signal: abortControllerRef.current.signal,
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            if (!response.body) {
                throw new Error("No response body");
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
                            // Mark streaming complete
                            setMessages(prev => {
                                const updated = [...prev];
                                const last = updated[updated.length - 1];
                                if (last?.role === "assistant") {
                                    updated[updated.length - 1] = {
                                        ...last,
                                        content: event.full_response || last.content,
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
                                        content: `Error: ${event.message}`,
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
            if (error.name === "AbortError") return;

            setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant") {
                    updated[updated.length - 1] = {
                        ...last,
                        content: "Sorry, I couldn't connect to the server. Make sure the backend is running.",
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
                        <div className={`max-w-[85%] rounded-2xl p-4 ${
                            msg.role === "user"
                                ? "bg-primary text-white rounded-br-none"
                                : "bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 rounded-bl-none shadow-sm"
                        }`}>
                            <div className="whitespace-pre-wrap text-sm leading-relaxed">
                                {msg.content}
                                {msg.streaming && (
                                    <span className="inline-block w-1.5 h-4 ml-0.5 bg-current animate-pulse rounded-sm" />
                                )}
                            </div>

                            {msg.role === "assistant" && !msg.streaming && msg.metrics && (
                                <div className="mt-4 pt-4 border-t border-slate-50 dark:border-slate-800">
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
            <form onSubmit={handleSend} className="fixed bottom-8 left-0 right-0 max-w-4xl mx-auto px-4">
                <div className="relative">
                    <input
                        type="text"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        disabled={loading}
                        placeholder="Ask about funds, documents, or timelines..."
                        className="w-full h-14 pl-6 pr-14 rounded-full border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-lg focus:outline-none focus:ring-2 focus:ring-primary/20 dark:shadow-none"
                    />
                    <button
                        type="submit"
                        disabled={loading || !query.trim()}
                        className="absolute right-2 top-2 h-10 w-10 flex items-center justify-center rounded-full bg-primary text-white disabled:opacity-50 transition-transform active:scale-95"
                    >
                        <Send className="h-4 w-4" />
                    </button>
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
