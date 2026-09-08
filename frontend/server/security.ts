import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import type { NextApiRequest, NextApiResponse } from "next";
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
export const production = () => process.env.NODE_ENV === "production";
export function origin(): string {
  const value = process.env.APP_ORIGIN;
  if (!value) throw new ApiError(503, "The service is not configured yet.");
  const u = new URL(value);
  if (production() && u.protocol !== "https:")
    throw new ApiError(503, "HTTPS configuration is required.");
  return u.origin;
}
export function secret(): string {
  const key = process.env.INTERNAL_API_SECRET;
  if (!key || key.length < 32)
    throw new ApiError(503, "The service is not configured yet.");
  return key;
}
export function name(key: string) {
  return `${production() ? "__Host-" : ""}mm-${key}`;
}
export function cookie(
  res: NextApiResponse,
  key: string,
  value: string,
  age = 2592000,
) {
  const current = res.getHeader("Set-Cookie");
  const list = Array.isArray(current)
    ? current
    : current
      ? [String(current)]
      : [];
  res.setHeader("Set-Cookie", [
    ...list,
    `${name(key)}=${encodeURIComponent(value)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${age}${production() ? "; Secure" : ""}`,
  ]);
}
export function sign(value: string) {
  return createHmac("sha256", secret()).update(value).digest("hex");
}
export function equal(a: string, b: string) {
  const left = Buffer.from(a),
    right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}
export function csrf(req: NextApiRequest, res: NextApiResponse) {
  let value = req.cookies[name("csrf")];
  const [random, signature] = value?.split(".") ?? [];
  if (!random || !signature || !equal(sign(random), signature)) {
    const token = randomBytes(24).toString("hex");
    value = `${token}.${sign(token)}`;
    cookie(res, "csrf", value, 86400);
  }
  return value!;
}
export function protect(req: NextApiRequest) {
  if (req.headers.origin !== origin())
    throw new ApiError(403, "This request did not come from this website.");
  const supplied = req.headers["x-csrf-token"];
  const stored = req.cookies[name("csrf")];
  if (typeof supplied !== "string" || !stored || !equal(supplied, stored))
    throw new ApiError(403, "Refresh this page and try again.");
  const [token, signature] = stored.split(".");
  if (!token || !signature || !equal(sign(token), signature))
    throw new ApiError(403, "Invalid request token.");
}
export function noStore(res: NextApiResponse) {
  res.setHeader("Cache-Control", "private, no-store, max-age=0");
  res.setHeader("Pragma", "no-cache");
}
export function fail(res: NextApiResponse, error: unknown) {
  noStore(res);
  res
    .status(error instanceof ApiError ? error.status : 503)
    .json({
      detail:
        error instanceof ApiError
          ? error.message
          : "The service is unavailable. Please try again.",
    });
}
