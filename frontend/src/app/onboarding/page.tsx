"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, User, GraduationCap, Clock, Wallet, FileText } from "lucide-react";
import Link from "next/link";

export default function OnboardingPage() {
    const router = useRouter();
    const [loading, setLoading] = useState(false);
    const [formData, setFormData] = useState({
        country: "Canada",
        degree: "Masters",
        gpa: "3.5",
        gapYears: "0",
        sponsor: "Parents",
        exams: "IELTS 7.5",
    });

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);

        // In a real app, we would POST to /api/v1/profile
        // For this demo, we'll store in local storage and navigate to summary
        localStorage.setItem("user_profile", JSON.stringify(formData));

        // Simulate API delay
        await new Promise(resolve => setTimeout(resolve, 800));
        router.push("/visa-risk");
    };

    return (
        <div className="max-w-2xl mx-auto py-12 px-4">
            <Link href="/" className="inline-flex items-center text-sm text-slate-500 hover:text-primary mb-8">
                <ArrowLeft className="mr-2 h-4 w-4" /> Back to Home
            </Link>

            <div className="space-y-2 mb-8">
                <h2 className="text-3xl font-bold tracking-tight">Create Your Profile</h2>
                <p className="text-slate-500">
                    Provide your academic and financial details to compute your visa risk.
                </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Destination */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                            <User className="h-4 w-4" /> Destination Country
                        </label>
                        <select
                            className="w-full p-2 rounded-md border border-slate-200 dark:bg-slate-900 dark:border-slate-800"
                            value={formData.country}
                            onChange={(e) => setFormData({ ...formData, country: e.target.value })}
                        >
                            <option value="Canada">Canada</option>
                            {/* Other countries hidden — Canada-only focus
                            <option value="UK">United Kingdom</option>
                            <option value="USA">USA</option>
                            <option value="Australia">Australia</option>
                            */}
                        </select>
                    </div>

                    {/* Degree */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                            <GraduationCap className="h-4 w-4" /> Target Degree
                        </label>
                        <select
                            className="w-full p-2 rounded-md border border-slate-200 dark:bg-slate-900 dark:border-slate-800"
                            value={formData.degree}
                            onChange={(e) => setFormData({ ...formData, degree: e.target.value })}
                        >
                            <option value="Bachelors">Bachelors</option>
                            <option value="Masters">Masters</option>
                            <option value="PhD">PhD</option>
                            <option value="Diploma">Diploma</option>
                        </select>
                    </div>

                    {/* GPA */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                            <FileText className="h-4 w-4" /> Last GPA / Percentage
                        </label>
                        <input
                            type="text"
                            className="w-full p-2 rounded-md border border-slate-200 dark:bg-slate-900 dark:border-slate-800"
                            placeholder="e.g. 3.8 / 4.0"
                            value={formData.gpa}
                            onChange={(e) => setFormData({ ...formData, gpa: e.target.value })}
                        />
                    </div>

                    {/* Gap Years */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                            <Clock className="h-4 w-4" /> Study Gap (Years)
                        </label>
                        <input
                            type="number"
                            className="w-full p-2 rounded-md border border-slate-200 dark:bg-slate-900 dark:border-slate-800"
                            placeholder="0"
                            value={formData.gapYears}
                            onChange={(e) => setFormData({ ...formData, gapYears: e.target.value })}
                        />
                    </div>

                    {/* Sponsor */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                            <Wallet className="h-4 w-4" /> Financial Sponsor
                        </label>
                        <select
                            className="w-full p-2 rounded-md border border-slate-200 dark:bg-slate-900 dark:border-slate-800"
                            value={formData.sponsor}
                            onChange={(e) => setFormData({ ...formData, sponsor: e.target.value })}
                        >
                            <option value="Parents">Parents</option>
                            <option value="Self">Self</option>
                            <option value="Loan">Education Loan</option>
                            <option value="Company">Company Sponsored</option>
                        </select>
                    </div>

                    {/* Exams */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                            <FileText className="h-4 w-4" /> Language Exams
                        </label>
                        <input
                            type="text"
                            className="w-full p-2 rounded-md border border-slate-200 dark:bg-slate-900 dark:border-slate-800"
                            placeholder="IELTS 7.5 / TOEFL 100"
                            value={formData.exams}
                            onChange={(e) => setFormData({ ...formData, exams: e.target.value })}
                        />
                    </div>
                </div>

                <button
                    type="submit"
                    disabled={loading}
                    className="w-full py-3 bg-primary text-white font-bold rounded-md hover:bg-primary/90 transition-opacity disabled:opacity-50"
                >
                    {loading ? "Computing Risk Analysis..." : "Continue to Risk Analysis"}
                </button>
            </form>
        </div>
    );
}
