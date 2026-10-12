"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
    LayoutDashboard,
    ShieldAlert,
    Map,
    ClipboardList,
    FileEdit,
    MessageSquare,
    BarChart3,
    LogOut,
    UserCircle,
    LogIn
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getUser, isAuthenticated, logout } from "@/lib/auth";

const navItems = [
    { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { name: "Visa Risk", href: "/visa-risk", icon: ShieldAlert },
    { name: "Destinations", href: "/destinations", icon: Map },
    { name: "Applications", href: "/applications", icon: ClipboardList },
    { name: "SOP Generator", href: "/sop", icon: FileEdit },
    { name: "Ask Pendu", href: "/chat", icon: MessageSquare },
    { name: "System Metrics", href: "/demo/metrics", icon: BarChart3 },
];

export function Sidebar() {
    const pathname = usePathname();
    const router = useRouter();
    const [user, setUser] = useState<any>(null);
    const [authed, setAuthed] = useState(false);

    useEffect(() => {
        setAuthed(isAuthenticated());
        setUser(getUser());
    }, [pathname]);

    // Don't show sidebar on landing page, onboarding, login or signup
    if (pathname === "/" || pathname === "/onboarding" || pathname === "/login" || pathname === "/signup") {
        return null;
    }

    const handleLogout = async () => {
        await logout();
        setUser(null);
        setAuthed(false);
        router.push("/login");
    };

    return (
        <div className="flex flex-col w-64 h-screen bg-slate-900 text-white shrink-0 sticky top-0">
            <div className="p-6">
                <h1 className="text-2xl font-black italic tracking-tighter text-blue-400">PENDU</h1>
                <p className="text-[10px] uppercase tracking-widest text-slate-500 font-bold mt-1">Intelligence Engine</p>
            </div>

            <nav className="flex-1 px-4 space-y-1 overflow-y-auto">
                {navItems.map((item) => {
                    const isActive = pathname === item.href;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={cn(
                                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                                isActive
                                    ? "bg-blue-600 text-white"
                                    : "text-slate-400 hover:text-white hover:bg-slate-800"
                            )}
                        >
                            <item.icon className="h-4 w-4" />
                            {item.name}
                        </Link>
                    );
                })}
            </nav>

            <div className="p-4 border-t border-slate-800 space-y-4">
                <div className="flex items-center gap-3 px-3">
                    <UserCircle className="h-8 w-8 text-slate-500 shrink-0" />
                    <div className="flex flex-col min-w-0">
                        <span className="text-xs font-bold truncate">
                            {user?.email ? user.email.split("@")[0] : (authed ? "User" : "Guest")}
                        </span>
                        <span className="text-[10px] text-slate-500 truncate">
                            {authed ? (user?.is_admin ? "Administrator" : "Standard Account") : "Unauthenticated"}
                        </span>
                    </div>
                </div>
                {authed ? (
                    <button
                        onClick={handleLogout}
                        className="flex items-center gap-3 px-3 py-2 text-sm font-medium text-slate-400 hover:text-white w-full transition-colors rounded-lg hover:bg-slate-800"
                    >
                        <LogOut className="h-4 w-4" />
                        Logout
                    </button>
                ) : (
                    <Link
                        href={`/login?redirect=${encodeURIComponent(pathname)}`}
                        className="flex items-center gap-3 px-3 py-2 text-sm font-medium text-blue-400 hover:text-blue-300 w-full transition-colors rounded-lg hover:bg-slate-800"
                    >
                        <LogIn className="h-4 w-4" />
                        Sign In
                    </Link>
                )}
            </div>
        </div>
    );
}
