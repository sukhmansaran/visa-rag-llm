/**
 * Server-side session helpers for the /api/auth route handlers (M0.7). Never imported by page code.
 *
 * Tokens live only in httpOnly cookies, so page JavaScript cannot read them:
 *   pendu_at  access token, sent with every request (path /), injected as Authorization by middleware.ts
 *   pendu_rt  refresh token, sent only to /api/auth (path /api/auth)
 */

import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/sessionCookies";

export { ACCESS_COOKIE, REFRESH_COOKIE };
const REFRESH_PATH = "/api/auth";

export const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");

export interface BackendTokens {
    access_token: string;
    refresh_token: string;
    user: Record<string, unknown>;
}

/** Seconds until the JWT's `exp` (no signature check: the backend verifies; this only sizes the cookie). */
export function secondsUntilExpiry(token: string): number {
    try {
        const payload = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf8"));
        return Math.max(0, Math.floor(payload.exp - Date.now() / 1000));
    } catch {
        return 0;
    }
}

/**
 * Secure (HTTPS-only) cookies when the request really arrived over HTTPS (directly or via a proxy's
 * x-forwarded-proto). A production build served over plain http (a local `next start`) would otherwise set
 * cookies the browser refuses to store. COOKIE_SECURE=true/false overrides.
 */
function isSecureRequest(request: NextRequest): boolean {
    if (process.env.COOKIE_SECURE) return process.env.COOKIE_SECURE === "true";
    const forwarded = request.headers.get("x-forwarded-proto")?.split(",")[0].trim();
    return (forwarded || request.nextUrl.protocol.replace(":", "")) === "https";
}

function cookieOptions(request: NextRequest, path: string, maxAge: number) {
    return {
        httpOnly: true,
        secure: isSecureRequest(request),
        sameSite: "lax" as const,
        path,
        maxAge,
    };
}

export function setSessionCookies(request: NextRequest, response: NextResponse, tokens: BackendTokens): void {
    response.cookies.set(ACCESS_COOKIE, tokens.access_token, cookieOptions(request, "/", secondsUntilExpiry(tokens.access_token)));
    response.cookies.set(REFRESH_COOKIE, tokens.refresh_token,
        cookieOptions(request, REFRESH_PATH, secondsUntilExpiry(tokens.refresh_token)));
}

export function clearSessionCookies(request: NextRequest, response: NextResponse): void {
    response.cookies.set(ACCESS_COOKIE, "", cookieOptions(request, "/", 0));
    response.cookies.set(REFRESH_COOKIE, "", cookieOptions(request, REFRESH_PATH, 0));
}

/** Headers for calling the backend on the user's behalf, keeping the client address for rate limiting. */
export function backendHeaders(request: NextRequest, extra: Record<string, string> = {}): Record<string, string> {
    const headers: Record<string, string> = { "Content-Type": "application/json", ...extra };
    const forwarded = request.headers.get("x-forwarded-for");
    if (forwarded) headers["X-Forwarded-For"] = forwarded;
    return headers;
}

/** Call a backend auth endpoint and pass its JSON (minus tokens) and status through. */
export async function callBackend(path: string, init: RequestInit): Promise<{ status: number; body: any }> {
    const response = await fetch(`${BACKEND_URL}${path}`, { ...init, cache: "no-store" });
    let body: any = null;
    try {
        body = await response.json();
    } catch {
        body = null;
    }
    return { status: response.status, body };
}

/** New tokens from the refresh cookie, or null if there is none or the backend refuses it. */
export async function refreshSession(request: NextRequest): Promise<BackendTokens | null> {
    const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
    if (!refresh) return null;
    const { status, body } = await callBackend("/api/v1/auth/refresh", {
        method: "POST",
        headers: backendHeaders(request),
        body: JSON.stringify({ refresh_token: refresh }),
    });
    return status === 200 && body?.access_token ? body : null;
}

/** A response for the browser: the user, never the tokens. */
export function sessionResponse(request: NextRequest, tokens: BackendTokens, status = 200): NextResponse {
    const response = NextResponse.json({ user: tokens.user }, { status });
    setSessionCookies(request, response, tokens);
    return response;
}
