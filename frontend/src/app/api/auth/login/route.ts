import { NextRequest, NextResponse } from "next/server";
import { backendHeaders, callBackend, sessionResponse, rejectCrossSite } from "@/lib/server/session";

/** Log in: the backend's tokens become httpOnly cookies; the browser receives only the user. */
export async function POST(request: NextRequest) {
    const refused = rejectCrossSite(request, { jsonBody: true });
    if (refused) return refused;
    const credentials = await request.json().catch(() => null);
    const { status, body } = await callBackend("/api/v1/auth/login", {
        method: "POST",
        headers: backendHeaders(request),
        body: JSON.stringify(credentials ?? {}),
    });
    if (status !== 200 || !body?.access_token) {
        return NextResponse.json({ detail: body?.detail ?? "Login failed." }, { status: status === 200 ? 502 : status });
    }
    return sessionResponse(request, body);
}
