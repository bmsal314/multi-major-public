import type { NextApiRequest, NextApiResponse } from "next";
import {
  session,
  clearSession,
  reauthenticate,
  rateLimit,
} from "../../../server/auth";
import {
  ApiError,
  fail,
  noStore,
  protect,
  secret,
} from "../../../server/security";
export const config = {
  api: { bodyParser: { sizeLimit: "1mb" }, responseLimit: "4mb" },
};
export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse,
) {
  noStore(res);
  try {
    const path = (req.query.path as string[]).join("/");
    if (
      !/^(profile|uploads|analyses(?:\/[0-9a-f-]{36})?|audits(?:\/[0-9a-f-]{36})?|plans(?:\/[0-9a-f-]{36})?|account(?:\/export)?)$/.test(
        path,
      )
    )
      throw new ApiError(404, "Not found.");
    if (!["GET", "POST", "PUT", "DELETE"].includes(req.method ?? ""))
      throw new ApiError(405, "Method not allowed.");
    if (req.method !== "GET") protect(req);
    const current = await session(req, res);
    if (!current) throw new ApiError(401, "Sign in again.");
    if (
      path === "account" &&
      req.method === "DELETE" &&
      req.body?.confirmation !== "DELETE"
    )
      throw new ApiError(422, "Type DELETE to confirm account deletion.");
    if (path === "account" && req.method === "DELETE") {
      await rateLimit(req, current.user.email!);
      await reauthenticate(current.user.email!, req.body?.current_password);
    }
    const query =
      path === "account/export"
        ? `?${new URLSearchParams({ table: String(req.query.table ?? "profile"), offset: String(req.query.offset ?? 0) })}`
        : "";
    const base = process.env.ENGINE_URL;
    if (!base)
      throw new ApiError(503, "The planning service is not configured.");
    const response = await fetch(`${base.replace(/\/$/, "")}/${path}${query}`, {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
        "x-internal-secret": secret(),
        Authorization: `Bearer ${current.token}`,
      },
      body: req.method === "GET" ? undefined : JSON.stringify(req.body ?? {}),
      signal: AbortSignal.timeout(55000),
    });
    const data = await response.json();
    if (response.ok && path === "account" && req.method === "DELETE")
      clearSession(res);
    if (path === "account/export")
      res.setHeader(
        "Content-Disposition",
        'attachment; filename="multi-major-data.json"',
      );
    return res.status(response.status).json(data);
  } catch (error) {
    return fail(res, error);
  }
}
