"use client";

import { useState } from "react";
import Image from "next/image";
import { Search, MapPin, GraduationCap, Heart, ExternalLink, Filter } from "lucide-react";

export default function DestinationsPage() {
    const [search, setSearch] = useState("");

    const destinations = [
        { id: 1, name: "Toronto, Canada", type: "City", desc: "Global hub for AI and Tech startups.", img: "https://images.unsplash.com/photo-1517090504586-fde19ea6066f?q=80&w=400&h=250&auto=format&fit=crop" },
        { id: 2, name: "University of Toronto", type: "University", desc: "Top-ranked institution globally for Engineering.", img: "https://images.unsplash.com/photo-1541339907198-e08756ebafe3?q=80&w=400&h=250&auto=format&fit=crop" },
        { id: 5, name: "Vancouver, Canada", type: "City", desc: "Stunning coastal city with world-class universities.", img: "https://images.unsplash.com/photo-1559511260-66a68e7e7840?q=80&w=400&h=250&auto=format&fit=crop" },
        { id: 6, name: "McGill University", type: "University", desc: "One of Canada's most prestigious research universities.", img: "https://images.unsplash.com/photo-1541339907198-e08756ebafe3?q=80&w=400&h=250&auto=format&fit=crop" },
        /* Other countries hidden — Canada-only focus
        { id: 3, name: "London, UK", type: "City", desc: "Historical academic capital with vibrant culture.", img: "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?q=80&w=400&h=250&auto=format&fit=crop" },
        { id: 4, name: "Oxford University", type: "University", desc: "Legendary academic excellence and research.", img: "https://images.unsplash.com/photo-1541339907198-e08756ebafe3?q=80&w=400&h=250&auto=format&fit=crop" },
        */
    ];

    return (
        <div className="p-8 space-y-8 max-w-7xl mx-auto">
            <header className="space-y-4">
                <h1 className="text-3xl font-bold tracking-tight">Destination Explorer</h1>
                <div className="flex gap-4">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 -transform -translate-y-1/2 h-4 w-4 text-slate-400" />
                        <input
                            type="text"
                            placeholder="Search Canadian cities and universities..."
                            className="w-full pl-10 pr-4 py-2 rounded-xl border border-slate-100 bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />
                    </div>
                    <button className="px-4 py-2 border border-slate-100 bg-white rounded-xl shadow-sm hover:bg-slate-50 transition-colors flex items-center gap-2">
                        <Filter className="h-4 w-4" /> Filters
                    </button>
                </div>
            </header>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {destinations.map((dest) => (
                    <div key={dest.id} className="group rounded-2xl border border-slate-100 bg-white overflow-hidden shadow-sm hover:shadow-md transition-all hover:-translate-y-1">
                        <div className="aspect-[16/10] bg-slate-100 relative overflow-hidden">
                            <Image
                                src={dest.img}
                                alt={dest.name}
                                fill
                                sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 25vw"
                                className="object-cover transition-transform duration-500 group-hover:scale-110"
                            />
                            <button className="absolute top-3 right-3 p-1.5 bg-white/80 backdrop-blur rounded-full text-slate-400 hover:text-red-500 transition-colors">
                                <Heart className="h-4 w-4" />
                            </button>
                            <div className="absolute bottom-3 left-3 px-2 py-0.5 bg-black/50 backdrop-blur text-white text-[10px] uppercase font-bold rounded">
                                {dest.type}
                            </div>
                        </div>
                        <div className="p-4 space-y-2">
                            <h3 className="font-bold text-slate-900 group-hover:text-primary transition-colors">{dest.name}</h3>
                            <p className="text-xs text-slate-500 line-clamp-2 leading-relaxed">
                                {dest.desc}
                            </p>
                            <div className="flex justify-between items-center pt-2">
                                <div className="flex items-center gap-1 text-[10px] text-slate-400 font-bold uppercase">
                                    <MapPin className="h-3 w-3" /> Canada
                                </div>
                                <button className="text-primary hover:text-primary/80">
                                    <ExternalLink className="h-4 w-4" />
                                </button>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
