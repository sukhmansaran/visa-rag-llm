/** Small helpers for pages that read and write the signed-in user's own rows through /api/v1 (M6.4). */

import { apiFetch } from "@/lib/auth";

export class ApiError extends Error {
    constructor(message: string, public status: number) {
        super(message);
    }
}

/** The server's own words when it gave any (a string `detail`, or the first validation message). */
async function reason(response: Response, fallback: string): Promise<string> {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
    return fallback;
}

/** JSON request; throws ApiError with a message that can be shown as it is. Returns null for 204. */
export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
    const { json, ...rest } = init;
    let response: Response;
    try {
        response = await apiFetch(path, json === undefined ? rest : { ...rest, body: JSON.stringify(json) });
    } catch {
        throw new ApiError("Could not reach the server. Check that it is running and try again.", 0);
    }
    if (response.status === 401) throw new ApiError("Please sign in to continue.", 401);
    if (!response.ok) throw new ApiError(await reason(response, `The request failed (HTTP ${response.status}).`), response.status);
    return (response.status === 204 ? null : await response.json()) as T;
}

/** "15 Jan 2027" for an ISO date or datetime; "" when there is none. */
export function formatDate(value?: string | null): string {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("en-CA", { day: "numeric", month: "short", year: "numeric" });
}
