"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle, ChevronRight, BarChart3, TrendingUp, AlertTriangle } from "lucide-react";
import Link from "next/link";
import { apiFetch, isAuthenticated } from "@/lib/auth";

interface RiskBucket {
    name: string;
    score: number; // 0-20
    flag?: string | null;
    fix?: string | null;
    fix_cta?: string | null;
}

interface VisaRiskSummaryData {
    overall_risk: string;
    score: number; // 0-100
    buckets: RiskBucket[];
    red_flags: string[];
    top_concern?: string | null;
}

export default function VisaRiskPage() {
    const [profile, setProfile] = useState<any>(null);
    const [riskData, setRiskData] = useState<VisaRiskSummaryData | null>(null);
    const [loading, setLoading] = useState(true);
    const [statusMessage, setStatusMessage] = useState<string | null>(null);

    useEffect(() => {
        async function fetchRiskAnalysis() {
            setLoading(true);
            const localData = localStorage.getItem("user_profile");
            const parsedLocal = localData ? JSON.parse(localData) : null;
            setProfile(parsedLocal);

            if (isAuthenticated()) {
                try {
                    let profileId = sessionStorage.getItem("user_profile_id");

                    if (!profileId) {
                        const profRes = await apiFetch("/api/v1/profile", {
                        });
                        if (profRes.ok) {
                            const profData = await profRes.json();
                            if (profData?.id) {
                                profileId = String(profData.id);
                                sessionStorage.setItem("user_profile_id", profileId);
                            }
                        }
                    }

                    if (profileId) {
                        const riskRes = await apiFetch(`/api/v1/visa-risk/${profileId}`, {
                        });
                        if (riskRes.ok) {
                            const data: VisaRiskSummaryData = await riskRes.json();
                            setRiskData(data);
                            setLoading(false);
                            return;
                        }
                    }
                } catch (err) {
                    console.warn("Could not fetch visa risk from backend:", err);
                }
            }

            // No fabricated fallback: risk scores only come from the backend's assessment of a saved profile
            setStatusMessage(
                !isAuthenticated()
                    ? "Sign in and complete onboarding to compute your visa risk analysis."
                    : parsedLocal
                    ? "We couldn't compute your risk analysis right now. Please try again shortly."
                    : "Please complete onboarding first to evaluate your visa risk."
            );
            setLoading(false);
        }

        fetchRiskAnalysis();
    }, []);

    if (loading) return <div className="p-12 text-center text-slate-500 font-medium">Computing Official Visa Risk Analysis...</div>;
    if (!riskData) {
        return (
            <div className="p-12 text-center text-slate-500 space-y-4">
                <p>{statusMessage || "Please complete onboarding first to evaluate your visa risk."}</p>
                <div className="flex justify-center gap-4 text-sm font-medium">
                    {!isAuthenticated() && <Link href="/login?redirect=/visa-risk" className="text-primary hover:underline">Sign in</Link>}
                    <Link href="/onboarding" className="text-primary hover:underline">Go to onboarding</Link>
                </div>
            </div>
        );
    }

    const riskColor =
        riskData.overall_risk === "Low"
            ? "text-emerald-700 bg-emerald-50 border-emerald-200"
            : riskData.overall_risk === "Medium"
            ? "text-amber-700 bg-amber-50 border-amber-200"
            : "text-rose-700 bg-rose-50 border-rose-200";

    const fixList = riskData.buckets.map(b => b.fix).filter(Boolean) as string[];

    return (
        <div className="max-w-4xl mx-auto py-12 px-4 space-y-8">
            <div className="flex justify-between items-end border-b border-slate-100 dark:border-slate-800 pb-6">
                <div className="space-y-1">
                    <h1 className="text-3xl font-bold tracking-tight">Visa Risk Analysis</h1>
                    <p className="text-slate-500 text-sm">
                        Total Score: {riskData.score}/100 | Destination: {profile?.country || "Canada"}
                    </p>
                </div>
                <div className={`px-4 py-2 rounded-full border ${riskColor} font-bold text-sm tracking-wide`}>
                    Risk Level: {riskData.overall_risk} ({riskData.score}%)
                </div>
            </div>

            {/* Main Score Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div className="space-y-6">
                    <h3 className="text-lg font-bold flex items-center gap-2">
                        <BarChart3 className="h-5 w-5 text-primary" /> Category Score Breakdown
                    </h3>
                    <div className="space-y-4">
                        {riskData.buckets.map((bucket) => (
                            <ScoreRow
                                key={bucket.name}
                                label={bucket.name}
                                score={bucket.score * 5} // Convert 0-20 to percentage
                            />
                        ))}
                    </div>
                </div>

                <div className="space-y-6">
                    <h3 className="text-lg font-bold flex items-center gap-2">
                        <AlertCircle className="h-5 w-5 text-amber-500" /> Identified Red Flags
                    </h3>
                    <div className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 space-y-4">
                        {riskData.red_flags.length > 0 ? (
                            riskData.red_flags.map((flag, idx) => (
                                <RedFlag
                                    key={idx}
                                    title={`Flag ${idx + 1}`}
                                    desc={flag}
                                />
                            ))
                        ) : (
                            <p className="text-sm text-emerald-600 flex items-center gap-2">
                                <CheckCircle className="h-4 w-4" /> No high-severity red flags detected in your profile.
                            </p>
                        )}
                    </div>
                </div>
            </div>

            {/* Recommendations */}
            <div className="bg-blue-600 text-white rounded-2xl p-8 shadow-xl">
                <div className="flex items-start justify-between">
                    <div className="space-y-4">
                        <h2 className="text-2xl font-bold">What to Fix Next</h2>
                        <ul className="space-y-3 text-sm leading-relaxed">
                            {fixList.slice(0, 4).map((fix, idx) => (
                                <li key={idx} className="flex items-start gap-3">
                                    <div className="h-2 w-2 bg-white rounded-full mt-1.5 shrink-0"></div>
                                    <span>{fix}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                    <TrendingUp className="h-16 w-16 opacity-20 shrink-0" />
                </div>
            </div>

            <div className="flex justify-end gap-4">
                <Link
                    href="/chat"
                    className="inline-flex h-12 items-center justify-center rounded-md bg-slate-950 dark:bg-slate-100 dark:text-slate-900 px-8 text-sm font-medium text-white shadow transition-colors hover:bg-slate-800"
                >
                    Ask Chatbot How to Mitigate Risks <ChevronRight className="ml-2 h-4 w-4" />
                </Link>
            </div>
        </div>
    );
}

function ScoreRow({ label, score }: { label: string; score: number }) {
    return (
        <div className="space-y-1">
            <div className="flex justify-between text-sm">
                <span className="font-medium">{label}</span>
                <span className="text-slate-500 font-mono text-xs">{score}/100</span>
            </div>
            <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div
                    className="h-full bg-primary transition-all duration-700"
                    style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
                ></div>
            </div>
        </div>
    );
}

function RedFlag({ title, desc }: { title: string; desc: string }) {
    return (
        <div className="flex gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
            <div className="space-y-1">
                <h4 className="text-sm font-bold text-slate-900 dark:text-slate-100">{title}</h4>
                <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">{desc}</p>
            </div>
        </div>
    );
}
