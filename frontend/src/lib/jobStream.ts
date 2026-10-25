/**
 * Answer jobs client (M0.6d): start a job, follow its progress events over SSE and reconnect
 * automatically after a dropped connection, resuming after the last event received (Last-Event-ID),
 * so no event is lost or shown twice.
 */

import { apiFetch } from "@/lib/auth";

export type JobEventType = "status" | "queue" | "step" | "chunk" | "guardrail_blocked" | "done" | "error" | "cancelled";

export interface JobEvent {
    id: string;
    type: JobEventType | string;
    data: any;
}

export type JobOutcome = "done" | "error" | "cancelled";

const TERMINAL = new Set(["done", "error", "cancelled"]);
const MAX_RECONNECT_ATTEMPTS = 30; // back-off caps at 10 s, so ~5 minutes of failed reconnects

export class JobRequestError extends Error {
    constructor(message: string, public status: number) {
        super(message);
    }
}

export async function startAnswerJob(body: {
    query: string;
    country?: string | null;
    university?: string | null;
    sessionId?: string | null;
}): Promise<{ job_id: string; session_id: string }> {
    const response = await apiFetch("/api/v1/chat/jobs", { method: "POST", body: JSON.stringify(body) });
    if (!response.ok) {
        // A limit refusal (429, M1.4) explains itself; show the server's words
        const detail = response.status === 429 ? await response.json().then(b => b?.detail).catch(() => null) : null;
        throw new JobRequestError(typeof detail === "string" ? detail : `Could not start the answer (HTTP ${response.status})`,
            response.status);
    }
    return response.json();
}

/** Place in line for a verified answer (M1.4), e.g. "You're #2 in line, about 3 min". */
export function describeQueue(data: { position?: number; eta_s?: number }): string {
    const minutes = Math.max(1, Math.ceil((data.eta_s ?? 0) / 60));
    const place = data.position === 1 ? "You're next in line" : `You're #${data.position} in line`;
    return `${place}, about ${minutes} min`;
}

export async function cancelJob(jobId: string): Promise<void> {
    await apiFetch(`/api/v1/chat/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}

/** Parse complete SSE blocks out of `buffer`; returns events and the unparsed remainder. */
export function parseSseBlocks(buffer: string): { events: JobEvent[]; rest: string } {
    const blocks = buffer.split("\n\n");
    const rest = blocks.pop() ?? "";
    const events: JobEvent[] = [];
    for (const block of blocks) {
        let id = "";
        let type = "";
        let data = "";
        for (const line of block.split("\n")) {
            if (line.startsWith(":")) continue; // heartbeat / comment
            if (line.startsWith("id: ")) id = line.slice(4);
            else if (line.startsWith("event: ")) type = line.slice(7);
            else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (!type) continue;
        try {
            events.push({ id, type, data: data ? JSON.parse(data) : {} });
        } catch {
            // ignore a malformed event rather than breaking the stream
        }
    }
    return { events, rest };
}

/**
 * Follow a job until it ends. Reconnects after network errors or a dropped stream, resuming after the
 * last event id seen. `onConnection` reports "connected" / "reconnecting" for the UI.
 */
export async function followJob(
    jobId: string,
    onEvent: (event: JobEvent) => void,
    options: { signal?: AbortSignal; onConnection?: (state: "connected" | "reconnecting") => void } = {},
): Promise<JobOutcome> {
    let lastId = "";
    let attempt = 0;
    while (true) {
        if (options.signal?.aborted) throw new DOMException("Aborted", "AbortError");
        try {
            const headers: Record<string, string> = {};
            if (lastId) headers["Last-Event-ID"] = lastId;
            // apiFetch renews an expired session, so a reconnect late in a long answer still works (M0.7)
            const response = await apiFetch(`/api/v1/chat/jobs/${encodeURIComponent(jobId)}/events`, {
                headers,
                signal: options.signal,
                cache: "no-store",
            });
            if (response.status === 401 || response.status === 403) {
                throw new JobRequestError("Your session has expired. Please sign in again.", response.status);
            }
            if (response.status === 404) throw new JobRequestError("This answer is no longer available.", 404);
            if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

            options.onConnection?.("connected");
            attempt = 0;
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
                const parsed = parseSseBlocks(buffer);
                buffer = parsed.rest;
                for (const event of parsed.events) {
                    if (event.id) lastId = event.id;
                    onEvent(event);
                    if (TERMINAL.has(event.type)) return event.type as JobOutcome;
                }
            }
            // The stream closed without a final event: reconnect and resume
        } catch (error: any) {
            if (error?.name === "AbortError" || error instanceof JobRequestError) throw error;
        }
        options.onConnection?.("reconnecting");
        attempt += 1;
        if (attempt > MAX_RECONNECT_ATTEMPTS) {
            throw new JobRequestError("Lost the connection to the answer service. Please try again.", 0);
        }
        const delay = Math.min(1000 * 2 ** (attempt - 1), 10_000);
        await new Promise((resolve) => setTimeout(resolve, delay));
    }
}

/**
 * User-facing label for what is happening now. Step events arrive when a step *finishes*, so the label
 * names the stage that follows it (the pipeline order is fixed); e.g. after the evidence check the model
 * is writing, which can take most of the time.
 */
export function describeStep(step: any): string {
    const next: Record<string, string> = {
        input_guardrail: "Understanding the question",
        intent: "Applying official rules",
        decomposition: "Applying official rules", // M2.3: verified questions with several parts, split first
        rules: "Checking recent answers",
        cache: "Checking travel records",
        tourist_db: "Searching official sources",
        retrieval: "Checking the evidence",
        evidence_gate: "Writing the answer",
        generation: "Checking the answer",
        output_guardrail: "Finishing",
        disclaimer: "Finishing",
    };
    // Triage (M1.2) runs after the guardrail and, when retrieval confidence is low, again after the evidence check
    if (step?.name === "triage") return step.stage === "retrieval" ? next.evidence_gate : next.input_guardrail;
    if (step?.name === "diagnostic") return `Diagnostic step ${step.n}${step.of ? ` of ${step.of}` : ""}`;
    return next[step?.name] ?? "Working";
}
