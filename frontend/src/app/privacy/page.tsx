import Link from "next/link";

// Privacy page (M6.6, D7). Every statement here describes what the code does; change both together.
// Retention figures: TRACE_RETENTION_DAYS=30, AGENT_CHECKPOINT_RETENTION_HOURS=24, ANSWER_JOB_TTL_SECONDS=3600,
// VERIFIED_CACHE_TTL_SECONDS=7 days, PENDU_BACKUP_KEEP=20 (backend/app/core/config.py, scripts/backup_now.py).

export const metadata = { title: "Privacy | Pendu" };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <section className="space-y-3">
            <h2 className="text-xl font-bold">{title}</h2>
            <div className="space-y-3 text-sm text-slate-600 leading-relaxed">{children}</div>
        </section>
    );
}

export default function PrivacyPage() {
    return (
        <div className="p-8 max-w-3xl mx-auto space-y-8">
            <header className="space-y-2">
                <h1 className="text-3xl font-bold tracking-tight">Privacy</h1>
                <p className="text-sm text-slate-500">What Pendu stores about you, for how long, and how to remove it.</p>
            </header>

            <Section title="Your data stays on this installation">
                <p>
                    Pendu runs its AI models on the same machine as the application. Your questions, profile and
                    conversations are not sent to any outside AI service, analytics service or advertiser.
                </p>
                <p>
                    The only requests Pendu makes to the internet are fetches of official pages (for example
                    canada.ca) from a fixed list. Those requests carry nothing from you: no part of your question,
                    profile or conversation.
                </p>
            </Section>

            <Section title="What is stored">
                <ul className="list-disc pl-5 space-y-2">
                    <li><strong>Account:</strong> your email address and a one-way hash of your password. The password itself is never stored.</li>
                    <li><strong>Profile:</strong> what you enter in onboarding, such as education, field of study and test scores.</li>
                    <li><strong>Conversations:</strong> your questions and Pendu&apos;s answers.</li>
                    <li><strong>Your own records:</strong> tracked applications, Statement of Purpose drafts and any files you upload.</li>
                    <li><strong>Request records:</strong> for each question, a technical record of how it was answered (steps, timings, model calls), with personal details such as emails, phone numbers and document numbers removed before it is saved.</li>
                    <li><strong>In your browser:</strong> session cookies that scripts on the page cannot read, your email for display, and a copy of your onboarding answers.</li>
                </ul>
            </Section>

            <Section title="How long it is kept">
                <ul className="list-disc pl-5 space-y-2">
                    <li>Account, profile, conversations and your own records: until you delete your account.</li>
                    <li>Request records: 30 days, then deleted automatically.</li>
                    <li>A paused question waiting for your reply: up to 24 hours.</li>
                    <li>Working data for an answer in progress: about one hour.</li>
                    <li>Answers to checked questions may be reused for up to 7 days. They are stored by question, not by person.</li>
                    <li>Backups made by the operator can contain your data after deletion until they are rotated out (the newest 20 backup sets are kept).</li>
                </ul>
            </Section>

            <Section title="Who can see it">
                <p>
                    You, and the operator of this installation. Administrators can read request records (with personal
                    details removed) to find and fix problems. Your data is not sold or shared.
                </p>
            </Section>

            <Section title="Your choices">
                <p>
                    On the <Link href="/account" className="text-primary hover:underline">Account page</Link> you can
                    download a copy of everything stored about you and delete your account. Deleting removes your
                    account, profile, conversations, records, uploads and request records at once and cannot be undone.
                </p>
                <p>
                    Pendu is operated in line with the principles of Canada&apos;s privacy law (PIPEDA): it collects
                    only what the service needs, keeps it only as long as stated here, and lets you see and remove it.
                    For a privacy question or request, contact the operator of this installation.
                </p>
            </Section>

            <p className="text-xs text-slate-400">
                See also the <Link href="/terms" className="hover:underline">terms of use</Link>.
            </p>
        </div>
    );
}
