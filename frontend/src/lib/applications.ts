/** The application tracker's rows and stages (M6.4), shared by the tracker page and the dashboard. */

export interface TrackedApplication {
    id: number;
    university_name: string;
    program_name: string;
    status: string;
    deadline: string | null;
    notes: string | null;
    updated_at: string;
}

// The stages the API accepts (backend application_schemas.py)
export const STAGES: { value: string; label: string; style: string }[] = [
    { value: "planning", label: "Planning", style: "bg-slate-100 text-slate-600" },
    { value: "preparing", label: "Preparing", style: "bg-blue-50 text-blue-600" },
    { value: "submitted", label: "Submitted", style: "bg-amber-50 text-amber-600" },
    { value: "admitted", label: "Admitted", style: "bg-green-50 text-green-600" },
    { value: "waitlisted", label: "Waitlisted", style: "bg-purple-50 text-purple-600" },
    { value: "rejected", label: "Rejected", style: "bg-red-50 text-red-600" },
];

/** A row stored before the stages were fixed may hold another word; it is shown as it is. */
export function stageOf(status: string) {
    return STAGES.find((s) => s.value === status) ?? { value: status, label: status, style: "bg-slate-100 text-slate-600" };
}

/** The nearest deadline that hasn't passed, among applications still in progress. */
export function nextDeadline(applications: TrackedApplication[], now = new Date()): TrackedApplication | null {
    const open = applications.filter(
        (a) => a.deadline && new Date(a.deadline) >= now && !["admitted", "rejected"].includes(a.status),
    );
    open.sort((a, b) => new Date(a.deadline!).getTime() - new Date(b.deadline!).getTime());
    return open[0] ?? null;
}
