type ApiError = { code?: string; message?: string; details?: unknown };

const baseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function getCookie(name: string) {
  if (typeof document === "undefined") return "";
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : "";
}

async function parseJsonOrThrow(res: Response) {
  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const text = await res.text();
    throw new Error(
      `Unexpected response format (${res.status}). Expected JSON but received: ${text.slice(
        0,
        120
      )}`
    );
  }
  return (await res.json()) as {
    success?: boolean;
    data?: unknown;
    error?: ApiError;
    detail?: string;
  };
}

function resolveErrorMessage(json: { error?: ApiError; detail?: string }) {
  if (json.error?.message) return json.error.message;
  if (json.detail) return json.detail;
  return "Request failed.";
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    cache: "no-store",
    credentials: "include",
  });
  const json = await parseJsonOrThrow(res);
  if (!res.ok || json.success === false) {
    throw new Error(resolveErrorMessage(json));
  }
  return json.data as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const csrfToken = getCookie("csrftoken");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (csrfToken) {
    headers["X-CSRFToken"] = csrfToken;
  }
  const res = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    credentials: "include",
  });
  const json = await parseJsonOrThrow(res);
  if (!res.ok || json.success === false) {
    throw new Error(resolveErrorMessage(json));
  }
  return json.data as T;
}
