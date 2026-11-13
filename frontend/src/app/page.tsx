import Link from "next/link";
import { ArrowRight, ShieldCheck, Zap, Database } from "lucide-react";

export default function LandingPage() {
    return (
        <div className="flex flex-col items-center justify-center">
            {/* Hero Section */}
            <section className="w-full py-12 md:py-24 lg:py-32 xl:py-48 bg-gradient-to-b from-blue-50 to-white dark:from-slate-900 dark:to-slate-950">
                <div className="container px-4 md:px-6 mx-auto text-center">
                    <div className="space-y-4">
                        <h1 className="text-4xl font-bold tracking-tighter sm:text-5xl md:text-6xl lg:text-7xl">
                            Pendu: The Deterministic <br />
                            <span className="text-primary italic">Visa Intelligence Engine</span>
                        </h1>
                        <p className="mx-auto max-w-[700px] text-slate-500 md:text-xl dark:text-slate-400">
                            An assistant for Canadian study permit and visa questions, running on local models.
                            Official sources. Fixed rules for key figures. Information, not legal advice.
                        </p>
                        <div className="flex justify-center gap-4 pt-4">
                            <Link
                                href="/onboarding"
                                className="inline-flex h-11 items-center justify-center rounded-md bg-primary px-8 text-sm font-medium text-primary-foreground shadow transition-colors hover:bg-primary/90"
                            >
                                Try Sample Profile <ArrowRight className="ml-2 h-4 w-4" />
                            </Link>
                            <Link
                                href="/chat"
                                className="inline-flex h-11 items-center justify-center rounded-md border border-slate-200 bg-white px-8 text-sm font-medium shadow-sm transition-colors hover:bg-slate-100 dark:border-slate-800 dark:bg-slate-950 dark:hover:bg-slate-800"
                            >
                                Ask a Question
                            </Link>
                        </div>
                    </div>
                </div>
            </section>

            {/* Proof Section */}
            <section className="w-full py-12 md:py-24 lg:py-32 bg-white dark:bg-slate-950">
                <div className="container px-4 md:px-6 mx-auto">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                        <div className="flex flex-col items-center text-center space-y-2 p-6 rounded-xl border border-slate-100 dark:border-slate-800 shadow-sm">
                            <div className="p-3 bg-blue-100 dark:bg-blue-900 rounded-full">
                                <ShieldCheck className="h-6 w-6 text-blue-600 dark:text-blue-400" />
                            </div>
                            <h3 className="text-xl font-bold">Source Verified</h3>
                            <p className="text-slate-500 dark:text-slate-400">
                                Answers come from saved copies of official IRCC and Government of Canada pages, each claim checked against its source and shown with a link.
                            </p>
                        </div>
                        <div className="flex flex-col items-center text-center space-y-2 p-6 rounded-xl border border-slate-100 dark:border-slate-800 shadow-sm">
                            <div className="p-3 bg-yellow-100 dark:bg-yellow-900 rounded-full">
                                <Zap className="h-6 w-6 text-yellow-600 dark:text-yellow-400" />
                            </div>
                            <h3 className="text-xl font-bold">Shows Its Work</h3>
                            <p className="text-slate-500 dark:text-slate-400">
                                Every answer lists the steps taken and what was verified, and says so plainly when a part could not be checked.
                            </p>
                        </div>
                        <div className="flex flex-col items-center text-center space-y-2 p-6 rounded-xl border border-slate-100 dark:border-slate-800 shadow-sm">
                            <div className="p-3 bg-green-100 dark:bg-green-900 rounded-full">
                                <Database className="h-6 w-6 text-green-600 dark:text-green-400" />
                            </div>
                            <h3 className="text-xl font-bold">Deterministic Rules</h3>
                            <p className="text-slate-500 dark:text-slate-400">
                                Key figures such as fees, funds and work hours come from a reviewed rules file, not from the model.
                            </p>
                        </div>
                    </div>
                </div>
            </section>

            <footer className="w-full py-6 border-t border-slate-100 dark:border-slate-800">
                <div className="container px-4 md:px-6 mx-auto flex flex-col md:flex-row justify-between items-center gap-4 text-sm text-slate-500">
                    <p>Pendu. Information only, not legal advice; for your case, consult a licensed RCIC or lawyer.</p>
                    <div className="flex gap-4">
                        <Link href="/privacy" className="hover:underline">Privacy</Link>
                        <Link href="/terms" className="hover:underline">Terms</Link>
                    </div>
                </div>
            </footer>
        </div>
    );
}
