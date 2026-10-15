import { NextRequest, NextResponse } from "next/server";
import {
    ACCESS_COOKIE,
    backendHeaders,
    callBackend,
    clearSessionCookies,
    refreshSession,
    secondsUntilExpiry,
    setSessionCookies,
} from "@/lib/server/session";

/** The signed-in user, renewing an expired access token if the refresh cookie allows. 401 if signed out. */
export async function GET(request: NextRequest) {
    let access = request.cookies.get(ACCESS_COOKIE)?.value;
    let renewed = null;
    if (!access || secondsUntilExpiry(access) < 5) {
        renewed = await refreshSession(request);
        access = renewed?.access_token;
    }
    if (!access) {
        const response = NextResponse.json({ user: null }, { status: 401 });
        clearSessionCookies(request, response);
        return response;
    }
    const { status, body } = await callBackend("/api/v1/auth/me", {
        method: "GET",
        headers: backendHeaders(request, { Authorization: `Bearer ${access}` }),
    });
    if (status !== 200) {
        const response = NextResponse.json({ user: null }, { status: 401 });
        clearSessionCookies(request, response);
        return response;
    }
    const response = NextResponse.json({ user: body });
    if (renewed) setSessionCookies(request, response, renewed);
    return response;
}
