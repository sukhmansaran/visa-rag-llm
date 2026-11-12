"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CalendarDays, ClipboardList, MessageSquare, ShieldAlert, TrendingUp } from "lucide-react";
import { getUser, isAuthenticated } from "@/lib/auth";
import { api, formatDate } from "@/lib/api";
import { TrackedApplication, nextDeadline, stageOf } from "@/lib/applications";

// Dashboard (M6.4): everything shown is read from the signed-in user's profile, risk assessment and tracker.
// A card whose data can't be loaded says so; nothing is filled in with sample values.

interface Risk {
    overall_risk: string;
    score: number;
    top_concern?: string | null;
    buckets: { name: string; score: number }[];
}

const RISK_STYLE: Record<string, string> = {
    Low: "bg-green-500/20 text-green-400 border-green-500/30",
    Medium: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    High: "bg-red-500/20 text-red-400 border-red-500/30",
};

export default function DashboardPage() {
    const [signedIn, setSignedIn] = useState<boolean | null>(null);
    const [name, setName] = useState<string | null>(null);
    const [hasProfile, setHasProfile] = useState<boolean | null>(null);
    const [risk, setRisk] = useState<Risk | null>(null);
    const [applications, setApplications] = useState<TrackedApplication[] | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const authed = isAuthenticated();
        setSignedIn(authed);
        if (!authed) return;
        setName(getUser()?.full_name ?? null);

        api<TrackedApplication[]>("/api/v1/applications")
            .then(setApplications)
            .catch((e) => (e?.status === 401 ? setSignedIn(false) : setError(e?.message ?? "Could not load your applications.")));

        api<{ id?: number | null; first_name?: string | null; education_level?: string | null }>("/api/v1/profile")
            .then(async (profile) => {
                if (profile?.first_name) setName(profile.first_name);
                const filled = Boolean(profile?.id && profile.education_level); // an empty profile has nothing to assess
                setHasProfile(filled);
                if (filled) setRisk(await api<Risk>(`/api/v1/visa-risk/${profile.id}`));
            })
            .catch((e) => {
                if (e?.status === 401) setSignedIn(false);
                else if (e?.status === 404) setHasProfile(false);
                else setError(e?.message ?? "Could not load your profile.");
            });
    }, []);

    if (signedIn === false) {
        return (
            <div className="p-8 max-w-3xl mx-auto">
                <div className="p-8 rounded-2xl border border-slate-100 bg-white text-center space-y-3">
                    <p className="text-sm text-slate-600">Sign in to see your dashboard.</p>
                    <Link href="/login?redirect=/dashboard" className="inline-block px-4 py-2 bg-primary text-white rounded-lg text-sm font-bold">
                        Sign In
                    </Link>
                </div>
            </div>
        );
    }

    const upcoming = applications ? nextDeadline(applications) : null;
    const stats = [
        { label: "Visa Risk", value: risk ? risk.overall_risk : hasProfile === false ? "Not assessed" : "...", icon: ShieldAlert },
        { label: "Applications", value: applications ? String(applications.length) : "...", icon: ClipboardList },
        { label: "Next Deadline", value: applications ? (upcoming ? formatDate(upcoming.deadline) : "None set") : "...", icon: CalendarDays },
    ];

    return (
        <div className="p-8 space-y-8 max-w-7xl mx-auto">
            <header>
                <h1 className="text-3xl font-bold tracking-tight">Welcome back{name ? `, ${name}` : ""}</h1>
                <p className="text-slate-500">Your Canada study plans at a glance.</p>
            </header>

            {error && <div role="alert" className="p-4 rounded-xl border border-red-100 bg-red-50 text-sm text-red-700">{error}</div>}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {stats.map((stat) => (
                    <div key={stat.label} className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm flex items-center justify-between">
                        <div className="space-y-1">
                            <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">{stat.label}</p>
                            <p className="text-2xl font-bold text-slate-800">{stat.value}</p>
                        </div>
                        <div className="p-3 rounded-xl bg-slate-50 text-slate-500">
                            <stat.icon className="h-6 w-6" />
                        </div>
                    </div>
                ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                <div className="lg:col-span-2 space-y-6">
                    <div className="p-8 rounded-3xl bg-slate-900 text-white shadow-xl relative overflow-hidden">
                        <div className="relative z-10 space-y-6">
                            <div className="flex justify-between items-start">
                                <div className="space-y-1">
                                    <h2 className="text-2xl font-bold">Visa Risk Summary</h2>
                                    <p className="text-slate-400 text-sm">Scored by fixed rules from your saved profile; an estimate, not a decision.</p>
                                </div>
                                {risk && (
                                    <div className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-widest border ${RISK_STYLE[risk.overall_risk] ?? "bg-white/10 text-white border-white/20"}`}>
                                        {risk.overall_risk} Risk
                                    </div>
                                )}
                            </div>

                            {risk ? (
                                <>
                                    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                                        <div className="p-4 bg-white/5 rounded-xl border border-white/10 space-y-2">
                                            <p className="text-[10px] text-slate-500 uppercase font-bold">Overall</p>
                                            <p className="text-sm font-medium">{risk.score} / 100</p>
                                        </div>
                                        {risk.buckets.map((bucket) => (
                                            <div key={bucket.name} className="p-4 bg-white/5 rounded-xl border border-white/10 space-y-2">
                                                <p className="text-[10px] text-slate-500 uppercase font-bold">{bucket.name}</p>
                                                <p className="text-sm font-medium">{bucket.score} / 20</p>
                                            </div>
                                        ))}
                                    </div>
                                    {risk.top_concern && <p className="text-sm text-slate-300">Top concern: {risk.top_concern}</p>}
                                    <Link href="/visa-risk" className="inline-flex items-center text-sm font-bold text-blue-400 hover:text-blue-300 transition-colors">
                                        View Detailed Report <ArrowRight className="ml-2 h-4 w-4" />
                                    </Link>
                                </>
                            ) : hasProfile === false ? (
                                <div className="space-y-3">
                                    <p className="text-sm text-slate-300">Complete your profile to get a risk assessment.</p>
                                    <Link href="/onboarding" className="inline-flex items-center text-sm font-bold text-blue-400 hover:text-blue-300">
                                        Go to onboarding <ArrowRight className="ml-2 h-4 w-4" />
                                    </Link>
                                </div>
                            ) : (
                                <p className="text-sm text-slate-400">{error ? "The assessment couldn't be loaded." : "Loading your assessment..."}</p>
                            )}
                        </div>
                        <TrendingUp className="absolute -bottom-4 -right-4 h-48 w-48 text-white/5" />
                    </div>

                    <div className="space-y-4">
                        <div className="flex justify-between items-center">
                            <h3 className="text-lg font-bold">Your Applications</h3>
                            <Link href="/applications" className="text-sm text-primary hover:underline">View all</Link>
                        </div>
                        {applications === null && !error && <p className="text-sm text-slate-400">Loading...</p>}
                        {applications?.length === 0 && (
                            <p className="p-4 rounded-xl border border-dashed border-slate-200 bg-white text-sm text-slate-500">
                                No applications yet. <Link href="/applications" className="text-primary hover:underline">Add one in the tracker.</Link>
                            </p>
                        )}
                        <div className="space-y-3">
                            {(applications ?? []).slice(0, 3).map((application) => {
                                const stage = stageOf(application.status);
                                return (
                                    <div key={application.id} className="p-4 rounded-xl border border-slate-100 bg-white flex items-center justify-between">
                                        <div className="flex items-center gap-4">
                                            <div className="p-2 bg-slate-50 rounded-lg">
                                                <ClipboardList className="h-5 w-5 text-slate-400" />
                                            </div>
                                            <div>
                                                <p className="text-sm font-bold">{application.university_name}</p>
                                                <p className="text-xs text-slate-500">{application.program_name}</p>
                                            </div>
                                        </div>
                                        <div className="text-right space-y-1">
                                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${stage.style}`}>{stage.label}</span>
                                            <p className="text-[10px] text-slate-400">
                                                {application.deadline ? `Deadline ${formatDate(application.deadline)}` : "No deadline set"}
                                            </p>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>

                <div className="space-y-6">
                    <div className="p-6 rounded-2xl bg-blue-50 border border-blue-100 space-y-4">
                        <h3 className="font-bold text-blue-900 flex items-center gap-2">
                            <MessageSquare className="h-5 w-5 text-blue-600" /> Need Help?
                        </h3>
                        <p className="text-xs text-blue-800 leading-relaxed">
                            Ask Pendu about Canadian study permits and visas. Answers are checked against official IRCC pages; this is
                            information, not legal advice.
                        </p>
                        <Link href="/chat" className="block w-full py-2 bg-blue-600 text-white text-center rounded-lg text-xs font-bold hover:bg-blue-700 transition-colors">
                            Start Chat
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    );
}
