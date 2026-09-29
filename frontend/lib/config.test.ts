import { afterEach, describe, expect, it, vi } from "vitest";

const ORIGINAL_ENV = process.env.NEXT_PUBLIC_API_BASE_URL;

async function loadConfig() {
  vi.resetModules();
  return import("./config");
}

describe("apiBaseUrl", () => {
  afterEach(() => {
    process.env.NEXT_PUBLIC_API_BASE_URL = ORIGINAL_ENV;
  });

  it("accepts a well-formed http URL", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";
    const { apiBaseUrl } = await loadConfig();
    expect(apiBaseUrl).toBe("http://localhost:8000");
  });

  it("strips a trailing slash so callers never produce a double slash", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000/";
    const { apiBaseUrl } = await loadConfig();
    expect(apiBaseUrl).toBe("http://localhost:8000");
  });

  it("accepts an https URL", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://careflow.example.com";
    const { apiBaseUrl } = await loadConfig();
    expect(apiBaseUrl).toBe("https://careflow.example.com");
  });

  it("throws a clear error when unset", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "";
    await expect(loadConfig()).rejects.toThrow(/NEXT_PUBLIC_API_BASE_URL is not set/);
  });

  it("throws a clear error when malformed", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "not a url";
    await expect(loadConfig()).rejects.toThrow(/not a valid URL/);
  });

  it("rejects a non-http(s) protocol", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "ftp://localhost:8000";
    await expect(loadConfig()).rejects.toThrow(/must use http or https/);
  });
});
