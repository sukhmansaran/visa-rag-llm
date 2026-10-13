"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, User, GraduationCap, Clock, Wallet, FileText } from "lucide-react";
import Link from "next/link";
import { getAuthHeaders, isAuthenticated } from "@/lib/auth";

/** Convert a GPA on the user's chosen scale to the backend's 10-point scale; null if invalid. */
function toTenPointGpa(raw: string, scale: string): number | null {
    const value = parseFloat(raw);
    if (Number.isNaN(value) || value < 0) return null;
    const max = scale === "4" ? 4 : scale === "100" ? 100 : 10;
    if (value > max) return null;
    return Math.round((value / max) * 10 * 100) / 100;
}

export default function OnboardingPage() {
    const router = useRouter();
    const [loading, setLoading] = useState(false);
    const [formData, setFormData] = useState({
        country: "Canada",
        degree: "Masters",
        gpa: "8.0",
        gpaScale: "10",
        workExperienceYears: "0",
        sponsor: "Parents",
        exams: "IELTS 7.5",
    });

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);

        localStorage.setItem("user_profile", JSON.stringify(formData));

        if (isAuthenticated()) {
            try {
                const gpaScale10 = toTenPointGpa(formData.gpa, formData.gpaScale);
                const workYears = parseInt(formData.workExperienceYears, 10);

                const res = await fetch("/api/v1/profile", {
                    method: "PUT",
                    headers: getAuthHeaders(),
                    body: JSON.stringify({
                        education_level: formData.degree.toLowerCase(),
                        gpa: gpaScale10,
                        work_experience: Number.isNaN(workYears) ? null : Math.max(0, workYears),
                        target_countries: { primary: formData.country },
                        test_scores: { language: formData.exams, sponsor: formData.sponsor },
                    }),
                });

                if (res.ok) {
                    const profileData = await res.json();
                    if (profileData?.id) {
                        sessionStorage.setItem("user_profile_id", String(profileData.id));
                    }
                }
            } catch (err) {
                console.warn("Could not sync profile to backend API:", err);
            }
        }

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
                            <FileText className="h-4 w-4" /> GPA / Percentage
                        </label>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                inputMode="decimal"
                                className="w-full p-2 rounded-md border border-slate-200 dark:bg-slate-900 dark:border-slate-800"
                                placeholder={formData.gpaScale === "100" ? "e.g. 78" : formData.gpaScale === "4" ? "e.g. 3.4" : "e.g. 8.5"}
                                value={formData.gpa}
                                onChange={(e) => setFormData({ ...formData, gpa: e.target.value })}
                            />
                            <select
                                aria-label="GPA scale"
                                className="p-2 rounded-md border border-slate-200 dark:bg-slate-900 dark:border-slate-800"
                                value={formData.gpaScale}
                                onChange={(e) => setFormData({ ...formData, gpaScale: e.target.value })}
                            >
                                <option value="10">out of 10</option>
                                <option value="4">out of 4</option>
                                <option value="100">percent</option>
                            </select>
                        </div>
                    </div>

                    {/* Work experience (the backend's gap-year assessment is based on this) */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                            <Clock className="h-4 w-4" /> Work Experience Since Graduation (Years)
                        </label>
                        <input
                            type="number"
                            min={0}
                            className="w-full p-2 rounded-md border border-slate-200 dark:bg-slate-900 dark:border-slate-800"
                            placeholder="0"
                            value={formData.workExperienceYears}
                            onChange={(e) => setFormData({ ...formData, workExperienceYears: e.target.value })}
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
