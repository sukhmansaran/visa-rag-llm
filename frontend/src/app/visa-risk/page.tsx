"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle, Info, ChevronRight, BarChart3, TrendingUp, AlertTriangle } from "lucide-react";
import Link from "next/link";

export default function VisaRiskPage() {
    const [profile, setProfile] = useState<any>(null);

    useEffect(() => {
        const data = localStorage.getItem("user_profile");
        if (data) setProfile(JSON.parse(data));
    }, []);

    if (!profile) return <div className="p-12 text-center">Loading Risk Analysis...</div>;

    // Mock Risk Computation
    const riskLevel = parseInt(profile.gapYears) > 2 || parseFloat(profile.gpa) < 3.0 ? "Medium" : "Low";
    const riskColor = riskLevel === "Low" ? "text-green-600 bg-green-50 border-green-200" : "text-amber-600 bg-amber-50 border-amber-200";

    return (
        <div className="max-w-4xl mx-auto py-12 px-4 space-y-8">
            <div className="flex justify-between items-end border-b border-slate-100 pb-6">
                <div className="space-y-1">
                    <h1 className="text-3xl font-bold font-mono uppercase tracking-tight">Visa Risk Analysis</h1>
                    <p className="text-slate-500">System ID: PIN-882-RAG | Destination: {profile.country}</p>
                </div>
                <div className={`px-4 py-2 rounded-full border ${riskColor} font-bold text-sm uppercase tracking-widest`}>
                    Risk Level: {riskLevel}
                </div>
            </div>

            {/* Main Score Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div className="space-y-6">
                    <h3 className="text-lg font-bold flex items-center gap-2">
                        <BarChart3 className="h-5 w-5" /> Score Breakdown
                    </h3>
                    <div className="space-y-4">
                        <ScoreRow label="Academic Strength" score={85} />
                        <ScoreRow label="Financial Stability" score={90} />
                        <ScoreRow label="Gap/Contiguity" score={profile.gapYears === "0" ? 100 : 70} />
                        <ScoreRow label="SOP Signal Strength" score={80} />
                        <ScoreRow label="Application Timing" score={95} />
                    </div>
                </div>

                <div className="space-y-6">
                    <h3 className="text-lg font-bold flex items-center gap-2">
                        <AlertCircle className="h-5 w-5" /> Identified Red Flags
                    </h3>
                    <div className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 space-y-4">
                        {parseInt(profile.gapYears) > 0 ? (
                            <RedFlag
                                title={`${profile.gapYears} Year Gap Detected`}
                                desc="Gaps over 6 months require verifiable work experience or medical justification."
                            />
                        ) : (
                            <p className="text-sm text-green-600 flex items-center gap-2"><CheckCircle className="h-4 w-4" /> No high-severity red flags detected in academics.</p>
                        )}
                        <RedFlag
                            title="Generic SOP Risk"
                            desc="Ensure the Statement of Purpose is not generated from a template. Authenticity is key for Canadian IRCC."
                        />
                    </div>
                </div>
            </div>

            {/* Recommendations */}
            <div className="bg-blue-600 text-white rounded-2xl p-8 shadow-xl">
                <div className="flex items-start justify-between">
                    <div className="space-y-4">
                        <h2 className="text-2xl font-bold">What to Fix Next</h2>
                        <ul className="space-y-3">
                            <li className="flex items-center gap-3">
                                <div className="h-2 w-2 bg-white rounded-full"></div>
                                Order your GIC (Guaranteed Investment Certificate) immediately.
                            </li>
                            <li className="flex items-center gap-3">
                                <div className="h-2 w-2 bg-white rounded-full"></div>
                                Draft a contiguous 5-year history for your work/study gap.
                            </li>
                            <li className="flex items-center gap-3">
                                <div className="h-2 w-2 bg-white rounded-full"></div>
                                Get an official CA evaluation for your properties.
                            </li>
                        </ul>
                    </div>
                    <TrendingUp className="h-16 w-16 opacity-20" />
                </div>
            </div>

            <div className="flex justify-end gap-4">
                <Link
                    href="/chat"
                    className="inline-flex h-12 items-center justify-center rounded-md bg-slate-950 px-8 text-sm font-medium text-white shadow transition-colors hover:bg-slate-800"
                >
                    Ask Specific Questions <ChevronRight className="ml-2 h-4 w-4" />
                </Link>
            </div>
        </div>
    );
}

function ScoreRow({ label, score }: { label: string, score: number }) {
    return (
        <div className="space-y-1">
            <div className="flex justify-between text-sm">
                <span className="font-medium">{label}</span>
                <span className="text-slate-500">{score}%</span>
            </div>
            <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div
                    className="h-full bg-primary transition-all duration-1000"
                    style={{ width: `${score}%` }}
                ></div>
            </div>
        </div>
    );
}

function RedFlag({ title, desc }: { title: string, desc: string }) {
    return (
        <div className="flex gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0" />
            <div className="space-y-1">
                <h4 className="text-sm font-bold">{title}</h4>
                <p className="text-xs text-slate-500 leading-relaxed">{desc}</p>
            </div>
        </div>
    );
}
