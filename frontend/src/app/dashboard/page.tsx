"use client";

import { useEffect, useState } from "react";
import {
    ShieldAlert,
    MapPin,
    ClipboardList,
    ArrowRight,
    TrendingUp,
    Clock,
    CheckCircle2,
    AlertCircle
} from "lucide-react";
import Link from "next/link";

export default function DashboardPage() {
    const [profile, setProfile] = useState<any>(null);

    useEffect(() => {
        const data = localStorage.getItem("user_profile");
        if (data) setProfile(JSON.parse(data));
    }, []);

    const stats = [
        { label: "Visa Risk", value: "Low", icon: ShieldAlert, color: "text-green-600", bg: "bg-green-50" },
        { label: "Active Apps", value: "3", icon: ClipboardList, color: "text-blue-600", bg: "bg-blue-50" },
        { label: "Watchlist", value: "8", icon: MapPin, color: "text-purple-600", bg: "bg-purple-50" },
    ];

    return (
        <div className="p-8 space-y-8 max-w-7xl mx-auto">
            <header className="flex justify-between items-end">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Welcome back, {profile?.name || "Sukhn"}</h1>
                    <p className="text-slate-500">Here is what is happening with your {profile?.country || "Canada"} application.</p>
                </div>
                <div className="text-right">
                    <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">Next Deadline</p>
                    <p className="text-sm font-bold text-red-500">Sept 15, 2025 (Tuition Payment)</p>
                </div>
            </header>

            {/* Stats Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {stats.map((stat) => (
                    <div key={stat.label} className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm flex items-center justify-between">
                        <div className="space-y-1">
                            <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">{stat.label}</p>
                            <p className={`text-2xl font-bold ${stat.color}`}>{stat.value}</p>
                        </div>
                        <div className={`p-3 rounded-xl ${stat.bg} ${stat.color}`}>
                            <stat.icon className="h-6 w-6" />
                        </div>
                    </div>
                ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Risk Card Mini */}
                <div className="lg:col-span-2 space-y-6">
                    <div className="p-8 rounded-3xl bg-slate-900 text-white shadow-xl relative overflow-hidden">
                        <div className="relative z-10 space-y-6">
                            <div className="flex justify-between items-start">
                                <div className="space-y-1">
                                    <h2 className="text-2xl font-bold">Visa Risk Summary</h2>
                                    <p className="text-slate-400 text-sm">Computed via Deterministic Rule Engine</p>
                                </div>
                                <div className="px-3 py-1 bg-green-500/20 text-green-400 rounded-full text-xs font-bold uppercase tracking-widest border border-green-500/30">
                                    Low Risk
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <div className="p-4 bg-white/5 rounded-xl border border-white/10 space-y-2">
                                    <p className="text-[10px] text-slate-500 uppercase font-bold">Financials</p>
                                    <p className="text-sm font-medium">CAD 20,635+ Verified</p>
                                </div>
                                <div className="p-4 bg-white/5 rounded-xl border border-white/10 space-y-2">
                                    <p className="text-[10px] text-slate-500 uppercase font-bold">Academic</p>
                                    <p className="text-sm font-medium">GPA 3.5 (Aligned)</p>
                                </div>
                            </div>

                            <Link
                                href="/visa-risk"
                                className="inline-flex items-center text-sm font-bold text-blue-400 hover:text-blue-300 transition-colors"
                            >
                                View Detailed Report <ArrowRight className="ml-2 h-4 w-4" />
                            </Link>
                        </div>
                        <TrendingUp className="absolute -bottom-4 -right-4 h-48 w-48 text-white/5" />
                    </div>

                    {/* Recent Applications */}
                    <div className="space-y-4">
                        <div className="flex justify-between items-center">
                            <h3 className="text-lg font-bold">Active Applications</h3>
                            <Link href="/applications" className="text-sm text-primary hover:underline">View all</Link>
                        </div>
                        <div className="space-y-3">
                            <ApplicationRow
                                name="University of Toronto"
                                sub="MSc Computer Science"
                                status="Under Review"
                                date="2 days ago"
                                icon={<Clock className="h-4 w-4 text-amber-500" />}
                            />
                            <ApplicationRow
                                name="McGill University"
                                sub="MSc Data Science"
                                status="Documents Verified"
                                date="1 week ago"
                                icon={<CheckCircle2 className="h-4 w-4 text-green-500" />}
                            />
                        </div>
                    </div>
                </div>

                {/* Sidebar Cards */}
                <div className="space-y-6">
                    <div className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm space-y-4">
                        <h3 className="font-bold flex items-center gap-2">
                            <MapPin className="h-5 w-5 text-purple-600" /> Watchlist
                        </h3>
                        <div className="space-y-3">
                            <WatchlistItem name="Vancouver, BC" type="City" />
                            <WatchlistItem name="UBC" type="University" />
                            <WatchlistItem name="Waterloo" type="University" />
                        </div>
                        <Link href="/destinations" className="block text-center text-xs font-bold text-slate-400 hover:text-primary pt-2 border-t border-slate-50">
                            Browse More
                        </Link>
                    </div>

                    <div className="p-6 rounded-2xl bg-blue-50 border border-blue-100 space-y-4">
                        <h3 className="font-bold text-blue-900 flex items-center gap-2">
                            <Zap className="h-5 w-5 text-blue-600" /> Need Help?
                        </h3>
                        <p className="text-xs text-blue-800 leading-relaxed">
                            Ask Pendu anything about your visa process. Our RAG system is updated with 2025 policies.
                        </p>
                        <Link
                            href="/chat"
                            className="block w-full py-2 bg-blue-600 text-white text-center rounded-lg text-xs font-bold hover:bg-blue-700 transition-colors"
                        >
                            Start Chat
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    );
}

function ApplicationRow({ name, sub, status, date, icon }: any) {
    return (
        <div className="p-4 rounded-xl border border-slate-100 bg-white flex items-center justify-between hover:border-primary/20 transition-colors group">
            <div className="flex items-center gap-4">
                <div className="p-2 bg-slate-50 rounded-lg group-hover:bg-primary/5">
                    <ClipboardList className="h-5 w-5 text-slate-400 group-hover:text-primary" />
                </div>
                <div>
                    <p className="text-sm font-bold">{name}</p>
                    <p className="text-xs text-slate-500">{sub}</p>
                </div>
            </div>
            <div className="text-right">
                <p className="flex items-center gap-1 text-[10px] font-bold text-slate-500 justify-end uppercase tracking-tighter">
                    {icon} {status}
                </p>
                <p className="text-[10px] text-slate-400">{date}</p>
            </div>
        </div>
    );
}

function WatchlistItem({ name, type }: any) {
    return (
        <div className="flex items-center justify-between group cursor-pointer">
            <div className="flex items-center gap-2">
                <div className="h-1.5 w-1.5 bg-purple-400 rounded-full"></div>
                <span className="text-xs font-medium text-slate-700 group-hover:text-primary">{name}</span>
            </div>
            <span className="text-[10px] text-slate-400 uppercase font-bold">{type}</span>
        </div>
    );
}

function Zap({ className }: any) {
    return (
        <svg
            className={className}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
        >
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
    );
}
