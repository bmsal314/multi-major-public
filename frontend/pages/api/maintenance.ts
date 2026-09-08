import type { NextApiRequest, NextApiResponse } from "next";
import { ApiError, equal, fail, noStore, secret } from "../../server/security";
export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse,
) {
  noStore(res);
  try {
    const cron = process.env.CRON_SECRET;
    if (
      req.method !== "GET" ||
      !cron ||
      cron.length < 32 ||
      !equal(req.headers.authorization ?? "", `Bearer ${cron}`)
    )
      throw new ApiError(403, "Forbidden.");
    if (!process.env.ENGINE_URL)
      throw new ApiError(503, "Service unavailable.");
    const r = await fetch(
      `${process.env.ENGINE_URL.replace(/\/$/, "")}/maintenance`,
      {
        method: "POST",
        headers: { "x-internal-secret": secret(), "x-cron-secret": cron },
        signal: AbortSignal.timeout(55000),
      },
    );
    return res.status(r.status).json(await r.json());
  } catch (e) {
    return fail(res, e);
  }
}
