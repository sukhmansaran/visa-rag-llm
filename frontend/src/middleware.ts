import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, CSRF_HEADER, CSRF_VALUE } from "@/lib/sessionCookies";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * Session cookie -> backend bearer token (M0.7). Requests to /api/v1/* are proxied to the backend by the
 * rewrite in next.config.mjs; this adds `Authorization: Bearer <access token>` from the httpOnly cookie, so
 * the backend stays token-based and page JavaScript never handles tokens.
 *
 * CSRF: cookies are sent automatically, so a state-changing request authenticated by the cookie must carry
 * our custom header (another site's page cannot set it without a CORS preflight the backend refuses).
 * Requests that already bring their own Authorization header (scripts, API clients) pass through untouched.
 */
export function middleware(request: NextRequest) {
    const access = request.cookies.get(ACCESS_COOKIE)?.value;
    if (!access || request.headers.has("authorization")) {
        return NextResponse.next();
    }
    if (!SAFE_METHODS.has(request.method) && request.headers.get(CSRF_HEADER) !== CSRF_VALUE) {
        return NextResponse.json({ detail: "Missing CSRF header." }, { status: 403 });
    }
    const headers = new Headers(request.headers);
    headers.set("authorization", `Bearer ${access}`);
    headers.delete("cookie"); // the backend doesn't use cookies; keep tokens out of its logs
    return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/v1/:path*" };
