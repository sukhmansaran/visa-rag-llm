"use client";

import Link from "next/link";
import { useState } from "react";
import { FileText, Wand2, ArrowRight, Save, Layout, ListChecks } from "lucide-react";

export default function SopGeneratorPage() {
    const [draft, setDraft] = useState("");
    const [loading, setLoading] = useState(false);

    const handleGenerate = () => {
        setLoading(true);
        // Simulate LLM delay
        setTimeout(() => {
            setDraft(
                "Statement of Purpose\n\nI am writing to express my strong interest in the MSc Computer Science program at the University of Toronto. With a solid foundation in software engineering and a passion for artificial intelligence..."
            );
            setLoading(false);
        }, 1500);
    };

    return (
        <div className="p-8 space-y-8 max-w-6xl mx-auto">
            <header className="flex justify-between items-center">
                <div className="space-y-1">
                    <h1 className="text-3xl font-bold tracking-tight">SOP Intelligence</h1>
                    <p className="text-slate-500 text-sm">Draft, optimize, and verify your Statement of Purpose using RAG-backed insights.</p>
                </div>
                <div className="flex gap-3">
                    <button className="flex items-center gap-2 px-4 py-2 border border-slate-100 bg-white rounded-xl shadow-sm hover:bg-slate-50 transition-colors text-xs font-bold">
                        <Save className="h-3 w-3" /> Save Draft
                    </button>
                    <button
                        onClick={handleGenerate}
                        disabled={loading}
                        className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl shadow-lg shadow-primary/20 hover:bg-primary/90 transition-all font-bold text-xs disabled:opacity-50"
                    >
                        <Wand2 className="h-3 w-3" /> {loading ? "Analyzing Profile..." : "AI Draft"}
                    </button>
                </div>
            </header>

            <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                {/* Editor Area */}
                <div className="lg:col-span-3 h-[calc(100vh-250px)]">
                    <div className="h-full rounded-2xl border border-slate-100 bg-white shadow-sm overflow-hidden flex flex-col">
                        <div className="px-4 py-3 border-b border-slate-50 bg-slate-50/50 flex justify-between items-center">
                            <span className="text-[10px] uppercase font-black text-slate-400">Statement of Purpose v1.0</span>
                            <div className="flex gap-2">
                                <div className="h-2 w-2 rounded-full bg-green-500"></div>
                                <div className="h-2 w-2 rounded-full bg-slate-200"></div>
                                <div className="h-2 w-2 rounded-full bg-slate-200"></div>
                            </div>
                        </div>
                        <textarea
                            className="flex-1 w-full p-8 resize-none focus:outline-none text-slate-800 leading-relaxed font-serif text-lg"
                            placeholder="Start drafting your story or use AI to generate a baseline based on your profile..."
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                        />
                    </div>
                </div>

                {/* Intelligence Sidebar */}
                <div className="space-y-6">
                    <div className="p-6 rounded-2xl bg-slate-900 text-white space-y-4">
                        <h4 className="font-bold flex items-center gap-2 text-blue-400 text-xs uppercase tracking-widest">
                            <ListChecks className="h-4 w-4" /> Checklist
                        </h4>
                        <ul className="space-y-3">
                            <li className="flex gap-2 text-[10px]">
                                <div className="mt-0.5 h-3 w-3 rounded-full border border-blue-400 flex items-center justify-center shrink-0">
                                    <div className="h-1.5 w-1.5 bg-blue-400 rounded-full"></div>
                                </div>
                                Academic Gap Explanation
                            </li>
                            <li className="flex gap-2 text-[10px]">
                                <div className="mt-0.5 h-3 w-3 rounded-full border border-slate-700 flex items-center justify-center shrink-0"></div>
                                Financial Source Mention
                            </li>
                            <li className="flex gap-2 text-[10px]">
                                <div className="mt-0.5 h-3 w-3 rounded-full border border-slate-700 flex items-center justify-center shrink-0"></div>
                                Future Career Goals in Home Country
                            </li>
                        </ul>
                    </div>

                    <div className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm space-y-4">
                        <h4 className="font-bold flex items-center gap-2 text-slate-900 text-xs uppercase tracking-widest">
                            <Layout className="h-4 w-4" /> RAG Insights
                        </h4>
                        <p className="text-[10px] text-slate-500 leading-relaxed italic">
                            &ldquo;University of Toronto 2025 Admissions prioritize research intent and alignment with the Vector Institute for AI applicants.&rdquo;
                        </p>
                        <Link href="/chat" className="text-[10px] text-primary font-bold hover:underline">Verify source &rarr;</Link>
                    </div>
                </div>
            </div>
        </div>
    );
}
