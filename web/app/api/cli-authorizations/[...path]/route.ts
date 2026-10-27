import { NextRequest } from "next/server";
import { localBoundary } from "@/lib/archive-server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ path: string[] }> };
export async function GET(request: NextRequest, context: Context) { return localBoundary(request, (await context.params).path.join("/"), "cli-authorization", "GET"); }
export async function POST(request: NextRequest, context: Context) { return localBoundary(request, (await context.params).path.join("/"), "cli-authorization", "POST"); }
