/** Memory BFF uses the existing trusted platform transport, never PowerContext credentials. */
import { cloudServerTransportReady, trustedServerRequest } from "@/lib/cloud-server-auth";
export const memoryServerTransportReady = cloudServerTransportReady;
export function memoryServerRequest(path: string, key: string, init?: { method?: "GET" | "POST"; body?: string }) {
  return trustedServerRequest(path, key, init, "memory");
}
