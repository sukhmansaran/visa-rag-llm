import { NextRequest, NextResponse } from "next/server";
import {
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    backendHeaders,
    callBackend,
    clearSessionCookies,
    refreshSession,
    rejectCrossSite,
    secondsUntilExpiry,
} from "@/lib/server/session";

/**
 * Log out: revoke the refresh token on the server, then clear the cookies. The backend's logout needs a
 * valid access token, so an expired one is renewed first. The cookies are cleared in every case.
 */
export async function POST(request: NextRequest) {
    const refused = rejectCrossSite(request);
    if (refused) return refused;
    let access = request.cookies.get(ACCESS_COOKIE)?.value;
    let refresh = request.cookies.get(REFRESH_COOKIE)?.value;

    if (refresh && (!access || secondsUntilExpiry(access) < 5)) {
        const renewed = await refreshSession(request);
        access = renewed?.access_token;
        refresh = renewed?.refresh_token;
    }
    if (access && refresh) {
        await callBackend("/api/v1/auth/logout", {
            method: "POST",
            headers: backendHeaders(request, { Authorization: `Bearer ${access}` }),
            body: JSON.stringify({ refresh_token: refresh }),
        }).catch(() => null);
    }
    const response = new NextResponse(null, { status: 204 });
    clearSessionCookies(request, response);
    return response;
}
