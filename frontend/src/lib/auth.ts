/**
 * Frontend session helpers (M0.7).
 *
 * Tokens are never handled here: the /api/auth route handlers keep them in httpOnly cookies and
 * middleware.ts turns the access cookie into the backend's Authorization header. Page code only keeps
 * the (non-secret) signed-in user for display, and calls the API through apiFetch, which adds the CSRF
 * header and renews an expired session once before giving up.
 */

import { CSRF_HEADER, CSRF_VALUE } from "@/lib/sessionCookies";

export interface AuthUser {
    id: number | string;
    email: string;
    full_name?: string | null;
    is_admin?: boolean;
    is_active?: boolean;
}

const USER_KEY = "pendu_auth_user";
// Written by the previous (localStorage) version; removed so no token stays readable by page scripts
const LEGACY_TOKEN_KEYS = ["pendu_access_token", "pendu_refresh_token"];

function storage(): Storage | null {
    return typeof window === "undefined" ? null : window.localStorage;
}

function removeLegacyTokens(): void {
    const s = storage();
    LEGACY_TOKEN_KEYS.forEach((key) => s?.removeItem(key));
}

export function getUser(): AuthUser | null {
    removeLegacyTokens();
    const raw = storage()?.getItem(USER_KEY);
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch {
        return null;
    }
}

function setUser(user: AuthUser | null): void {
    const s = storage();
    if (!s) return;
    if (user) s.setItem(USER_KEY, JSON.stringify(user));
    else s.removeItem(USER_KEY);
}

/** Whether a user is signed in on this device (the server still checks every request). */
export function isAuthenticated(): boolean {
    return getUser() !== null;
}

function withSessionHeaders(init: RequestInit = {}): RequestInit {
    const headers = new Headers(init.headers);
    headers.set(CSRF_HEADER, CSRF_VALUE);
    if (typeof init.body === "string" && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    return { ...init, headers, credentials: "same-origin" };
}

let refreshInFlight: Promise<boolean> | null = null;

/**
 * Renew the session from the refresh cookie. Concurrent callers share one request: refresh tokens are
 * single-use, so two parallel refreshes would invalidate each other.
 */
export function refreshSession(): Promise<boolean> {
    if (!refreshInFlight) {
        refreshInFlight = fetch("/api/auth/refresh", withSessionHeaders({ method: "POST" }))
            .then(async (response) => {
                if (!response.ok) {
                    setUser(null);
                    return false;
                }
                const data = await response.json().catch(() => null);
                if (data?.user) setUser(data.user);
                return true;
            })
            .catch(() => false)
            .finally(() => {
                refreshInFlight = null;
            });
    }
    return refreshInFlight;
}

/** fetch() for /api/v1: session cookie + CSRF header; on 401, renew the session once and retry. */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
    const response = await fetch(input, withSessionHeaders(init));
    if (response.status !== 401) return response;
    if (!(await refreshSession())) return response;
    return fetch(input, withSessionHeaders(init));
}

async function authenticate(path: string, body: Record<string, string>): Promise<AuthUser> {
    const response = await fetch(path, withSessionHeaders({ method: "POST", body: JSON.stringify(body) }));
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data?.user) {
        const detail = Array.isArray(data?.detail) ? data.detail[0]?.msg : data?.detail;
        throw new Error(detail || "Request failed.");
    }
    setUser(data.user);
    return data.user;
}

export function login(email: string, password: string): Promise<AuthUser> {
    return authenticate("/api/auth/login", { email, password });
}

export function signup(email: string, password: string): Promise<AuthUser> {
    return authenticate("/api/auth/signup", { email, password });
}

/** The signed-in user according to the server (renews an expired access token), or null. */
export async function loadSession(): Promise<AuthUser | null> {
    try {
        const response = await fetch("/api/auth/session", withSessionHeaders({ cache: "no-store" }));
        const data = await response.json().catch(() => null);
        setUser(response.ok ? data?.user ?? null : null);
    } catch {
        // offline: keep what we have
    }
    return getUser();
}

/** Revoke the session on the server and clear it here. Never throws. */
export async function logout(): Promise<void> {
    try {
        await fetch("/api/auth/logout", withSessionHeaders({ method: "POST" }));
    } catch {
        // network failure: still clear the local state below
    }
    setUser(null);
}

/**
 * Return a same-origin path that is safe to redirect to after login/signup.
 * Rejects absolute URLs, protocol-relative URLs ("//evil.com"), backslash tricks
 * ("/\evil.com") and anything that isn't a plain in-app path.
 */
export function safeRedirectPath(raw: string | null | undefined, fallback = "/chat"): string {
    if (!raw) return fallback;
    const value = raw.trim();
    if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
        return fallback;
    }
    if (!/^\/[A-Za-z0-9_\-./?=&%#]*$/.test(value)) {
        return fallback;
    }
    return value;
}
