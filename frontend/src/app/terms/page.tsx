import Link from "next/link";

// Terms of use (M6.6): above all, that Pendu gives information and not legal advice.

export const metadata = { title: "Terms | Pendu" };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <section className="space-y-3">
            <h2 className="text-xl font-bold">{title}</h2>
            <div className="space-y-3 text-sm text-slate-600 leading-relaxed">{children}</div>
        </section>
    );
}

export default function TermsPage() {
    return (
        <div className="p-8 max-w-3xl mx-auto space-y-8">
            <header className="space-y-2">
                <h1 className="text-3xl font-bold tracking-tight">Terms of use</h1>
                <p className="text-sm text-slate-500">Please read this before relying on anything Pendu tells you.</p>
            </header>

            <div className="p-5 rounded-xl border border-amber-200 bg-amber-50 text-sm text-amber-900 leading-relaxed">
                <strong>Information, not legal advice.</strong> Pendu explains what official Canadian immigration sources
                say. It is not a lawyer or a licensed immigration consultant, and it does not know your full situation.
                For advice about your own case, consult a Regulated Canadian Immigration Consultant (RCIC) or an
                immigration lawyer.
            </div>

            <Section title="What Pendu is">
                <p>
                    An AI assistant for questions about Canadian study permits and visas. It answers from saved copies
                    of official pages and a reviewed set of key figures, and shows the source for what it says.
                </p>
            </Section>

            <Section title="What it cannot promise">
                <ul className="list-disc pl-5 space-y-2">
                    <li>Answers can be wrong, incomplete or out of date. Immigration rules, fees and processing times change, and a saved copy of a page can lag behind the live one.</li>
                    <li>A &ldquo;verified&rdquo; mark means the statement was found word for word on the cited official page. It does not mean the statement applies to you.</li>
                    <li>The visa risk assessment is a rule-based estimate from what you entered. It does not predict any decision by Immigration, Refugees and Citizenship Canada (IRCC).</li>
                    <li>A Statement of Purpose draft is a starting point written by an AI model. It is not checked against official sources; review and rewrite it yourself.</li>
                    <li>Pendu is not affiliated with IRCC or the Government of Canada.</li>
                </ul>
            </Section>

            <Section title="Your part">
                <ul className="list-disc pl-5 space-y-2">
                    <li>Check anything important against the official source linked in the answer before you act on it.</li>
                    <li>Do not use Pendu to prepare false statements or documents for an application.</li>
                    <li>Keep your password to yourself; you are responsible for activity in your account.</li>
                </ul>
            </Section>

            <Section title="Availability">
                <p>
                    Pendu is provided as it is, without a guarantee that it is available, uninterrupted or free of
                    errors. To the extent the law allows, the operator is not liable for decisions made on the basis
                    of its answers.
                </p>
            </Section>

            <p className="text-xs text-slate-400">
                See also how your data is handled on the <Link href="/privacy" className="hover:underline">privacy page</Link>.
            </p>
        </div>
    );
}
