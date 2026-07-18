import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, login, fetchMe, listLeads, normalizeApiUrl } from "./api";

/** Build a minimal Response-like object for the mocked fetch. */
function jsonResponse(
  body: unknown,
  { ok = true, status = 200 }: { ok?: boolean; status?: number } = {},
): Response {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("normalizeApiUrl", () => {
  it("prepends https:// to a bare host (Render fromService injects one)", () => {
    expect(normalizeApiUrl("sterling-api.onrender.com")).toBe("https://sterling-api.onrender.com");
  });

  it("preserves an explicit scheme and strips a trailing slash", () => {
    expect(normalizeApiUrl("https://api.example.com/")).toBe("https://api.example.com");
    expect(normalizeApiUrl("http://127.0.0.1:8000")).toBe("http://127.0.0.1:8000");
  });

  it("falls back to localhost when unset or empty", () => {
    expect(normalizeApiUrl(undefined)).toBe("http://127.0.0.1:8000");
    expect(normalizeApiUrl("   ")).toBe("http://127.0.0.1:8000");
  });
});

describe("api request()", () => {
  it("returns parsed JSON on a successful response", async () => {
    const payload = {
      access_token: "tok",
      token_type: "bearer",
      user: {
        id: "1",
        name: "Jane",
        email: "jane@gmail.com",
        skills: [],
        portfolio_summary: null,
        is_active: true,
        created_at: "2026-01-01T00:00:00",
      },
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    const res = await login({ email: "jane@gmail.com", password: "secret123" });
    expect(res.access_token).toBe("tok");

    // Content-Type is set and credentials are included for cookie auth.
    const [, init] = fetchMock.mock.calls[0]!;
    const headers = init.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.credentials).toBe("include");
  });

  it("attaches a Bearer token when one is provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        id: "1",
        name: "Jane",
        email: "jane@gmail.com",
        skills: [],
        portfolio_summary: null,
        is_active: true,
        created_at: "2026-01-01T00:00:00",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchMe("my-token");
    const [, init] = fetchMock.mock.calls[0]!;
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer my-token");
  });

  it("throws ApiError with the server detail string on a 4xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: "Invalid email or password" }, { ok: false, status: 401 }),
      ),
    );

    await expect(login({ email: "x@gmail.com", password: "bad" })).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      message: "Invalid email or password",
    });
  });

  it("flattens FastAPI validation error arrays into a single message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: [{ msg: "field required" }, { msg: "too short" }] },
          { ok: false, status: 422 },
        ),
      ),
    );

    await expect(
      login({ email: "x@gmail.com", password: "" }),
    ).rejects.toThrowError(/field required; too short/);
  });

  it("maps a 401 (non-auth path) to a friendly credential message and fires unauthorized event", async () => {
    const listener = vi.fn();
    window.addEventListener("sterling:unauthorized", listener);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({}, { ok: false, status: 401 })),
    );

    await expect(listLeads("stale-token")).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener("sterling:unauthorized", listener);
  });

  it("translates a fetch network failure into an actionable message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(fetchMe("t")).rejects.toThrowError(/Cannot reach API/);
  });

  it("labels 5xx responses as a database/connection failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "boom" }, { ok: false, status: 503 })),
    );

    await expect(fetchMe("t")).rejects.toThrowError(/Database connection failed/);
  });
});
