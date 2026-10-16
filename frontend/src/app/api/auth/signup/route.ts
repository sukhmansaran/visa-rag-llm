import { NextRequest, NextResponse } from "next/server";
import { backendHeaders, callBackend, sessionResponse, rejectCrossSite } from "@/lib/server/session";

/** Sign up: the backend's tokens become httpOnly cookies; the browser receives only the user. */
export async function POST(request: NextRequest) {
    const refused = rejectCrossSite(request, { jsonBody: true });
    if (refused) return refused;
    const details = await request.json().catch(() => null);
    const { status, body } = await callBackend("/api/v1/auth/signup", {
        method: "POST",
        headers: backendHeaders(request),
        body: JSON.stringify(details ?? {}),
    });
    if (status !== 201 || !body?.access_token) {
        return NextResponse.json({ detail: body?.detail ?? "Signup failed." }, { status: status === 201 ? 502 : status });
    }
    return sessionResponse(request, body, 201);
}
