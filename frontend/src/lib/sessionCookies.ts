/** Cookie and header names shared by the auth route handlers and middleware (M0.7). */
export const ACCESS_COOKIE = "pendu_at";
export const REFRESH_COOKIE = "pendu_rt";
/** Sent by our page code on state-changing requests; another site's page cannot add it (CSRF guard). */
export const CSRF_HEADER = "x-requested-with";
export const CSRF_VALUE = "pendu";
