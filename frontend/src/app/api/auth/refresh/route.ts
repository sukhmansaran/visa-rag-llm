import { NextRequest, NextResponse } from "next/server";
import { clearSessionCookies, refreshSession, sessionResponse } from "@/lib/server/session";

/** Exchange the refresh cookie for new tokens (rotation: the old refresh token stops working). */
export async function POST(request: NextRequest) {
    const tokens = await refreshSession(request);
    if (!tokens) {
        const response = NextResponse.json({ detail: "Session expired." }, { status: 401 });
        clearSessionCookies(request, response);
        return response;
    }
    return sessionResponse(request, tokens);
}
