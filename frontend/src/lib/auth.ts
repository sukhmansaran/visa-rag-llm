/**
 * Frontend Authentication Helpers
 * Manages JWT tokens, user session storage, and authenticated headers.
 */

export interface AuthUser {
    id: number | string;
    email: string;
    full_name?: string | null;
    is_admin?: boolean;
    is_active?: boolean;
}

export interface AuthTokens {
    access_token: string;
    refresh_token?: string;
    token_type?: string;
    user?: AuthUser;
}

const ACCESS_TOKEN_KEY = "pendu_access_token";
const REFRESH_TOKEN_KEY = "pendu_refresh_token";
const USER_KEY = "pendu_auth_user";

export function getToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function getUser(): AuthUser | null {
    if (typeof window === "undefined") return null;
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch {
        return null;
    }
}

export function setAuth(tokens: AuthTokens): void {
    if (typeof window === "undefined") return;
    if (tokens.access_token) {
        localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
    }
    if (tokens.refresh_token) {
        localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
    }
    if (tokens.user) {
        localStorage.setItem(USER_KEY, JSON.stringify(tokens.user));
    }
}

export function clearAuth(): void {
    if (typeof window === "undefined") return;
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
}

export function isAuthenticated(): boolean {
    return Boolean(getToken());
}

export function getAuthHeaders(): Record<string, string> {
    const token = getToken();
    const headers: Record<string, string> = {
        "Content-Type": "application/json",
    };
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    return headers;
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

/** Revoke the refresh token server-side, then clear local session state. Never throws. */
export async function logout(): Promise<void> {
    const refreshToken = getRefreshToken();
    if (refreshToken && getToken()) {
        try {
            await fetch("/api/v1/auth/logout", {
                method: "POST",
                headers: getAuthHeaders(),
                body: JSON.stringify({ refresh_token: refreshToken }),
            });
        } catch {
            // Network failure: still clear the local session below
        }
    }
    clearAuth();
}
