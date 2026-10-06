"use client";

import Link from "next/link";
import {
    ClipboardList,
    Clock,
    CheckCircle2,
    AlertCircle,
    ChevronRight,
    Plus,
    ArrowUpRight
} from "lucide-react";

export default function ApplicationsPage() {
    const applications = [
        { id: 1, name: "University of Toronto", program: "MSc Computer Science", status: "Under Review", lastUpdate: "Oct 12, 2024", progress: 65, color: "text-amber-500", bg: "bg-amber-50" },
        { id: 2, name: "McGill University", program: "MSc Data Science", status: "Verified", lastUpdate: "Oct 08, 2024", progress: 45, color: "text-blue-500", bg: "bg-blue-50" },
        { id: 3, name: "Visa - Canada", program: "Study Permit (SDS)", status: "Approved", lastUpdate: "Nov 02, 2024", progress: 100, color: "text-green-500", bg: "bg-green-50" },
        { id: 4, name: "University of British Columbia", program: "MSc AI", status: "Under Review", lastUpdate: "Oct 15, 2024", progress: 50, color: "text-amber-500", bg: "bg-amber-50" },
    ];

    return (
        <div className="p-8 space-y-8 max-w-5xl mx-auto">
            <header className="flex justify-between items-center">
                <div className="space-y-1">
                    <h1 className="text-3xl font-bold tracking-tight">Application Tracker</h1>
                    <p className="text-slate-500 text-sm">Monitor your academic and visa milestones in one place.</p>
                </div>
                <button className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl shadow-lg shadow-primary/20 hover:bg-primary/90 transition-all font-bold text-sm">
                    <Plus className="h-4 w-4" /> New Application
                </button>
            </header>

            <div className="space-y-4">
                {applications.map((app) => (
                    <div key={app.id} className="p-6 rounded-2xl border border-slate-100 bg-white shadow-sm hover:shadow-md transition-shadow group cursor-pointer">
                        <div className="flex items-start justify-between gap-4">
                            <div className="flex gap-4">
                                <div className={`p-4 rounded-xl ${app.bg} ${app.color}`}>
                                    <ClipboardList className="h-6 w-6" />
                                </div>
                                <div className="space-y-1">
                                    <h3 className="font-bold text-lg group-hover:text-primary transition-colors">{app.name}</h3>
                                    <p className="text-sm text-slate-500">{app.program}</p>
                                    <div className="flex items-center gap-4 pt-2">
                                        <span className={`flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest ${app.color}`}>
                                            {app.status === "Approved" ? <CheckCircle2 className="h-3 w-3" /> : <Clock className="h-3 w-3" />}
                                            {app.status}
                                        </span>
                                        <span className="text-[10px] text-slate-400 font-bold uppercase tracking-widest">Update: {app.lastUpdate}</span>
                                    </div>
                                </div>
                            </div>
                            <ArrowUpRight className="h-5 w-5 text-slate-300 group-hover:text-primary transition-colors" />
                        </div>

                        <div className="mt-6 space-y-2">
                            <div className="flex justify-between text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                                <span>Completion Status</span>
                                <span>{app.progress}%</span>
                            </div>
                            <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                                <div
                                    className={`h-full transition-all duration-1000 ${app.progress === 100 ? "bg-green-500" : "bg-primary"}`}
                                    style={{ width: `${app.progress}%` }}
                                ></div>
                            </div>
                        </div>
                    </div>
                ))}
            </div>

            <div className="p-6 rounded-2xl bg-slate-900 text-white flex items-center justify-between">
                <div className="space-y-1">
                    <h4 className="font-bold flex items-center gap-2 uppercase tracking-widest text-xs text-blue-400">
                        <AlertCircle className="h-3 w-3" /> Missing Documents
                    </h4>
                    <p className="text-sm text-slate-300">Your SOP for UBC is still incomplete.</p>
                </div>
                <Link href="/sop" className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-bold transition-colors">
                    Draft Now
                </Link>
            </div>
        </div>
    );
}
