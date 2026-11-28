// Local layout/API preview. OAuth deliberately remains native-build only.
import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { readFile } from "node:fs/promises";
import { resolve, dirname, sep, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
const root = resolve(dirname(fileURLToPath(import.meta.url)), ".."),
  require = createRequire(import.meta.url);
if (process.argv.includes("--build")) {
  const build = spawnSync(
    process.execPath,
    [
      require.resolve("expo/bin/cli"),
      "export",
      "--platform",
      "web",
      "--output-dir",
      "dist-preview",
    ],
    {
      cwd: root,
      stdio: "inherit",
      env: { ...process.env, EXPO_PUBLIC_PREVIEW_PROXY: "1" },
    },
  );
  if (build.status !== 0) process.exit(build.status || 1);
  process.exit(0);
}
const base = new URL(
  process.env.BSA_PREVIEW_API_URL || "http://127.0.0.1:8765",
);
if (
  base.protocol !== "https:" &&
  !(base.protocol === "http:" && base.hostname === "127.0.0.1")
)
  throw new Error("Use HTTPS or the local Docker API.");
const allowed = new Set([
  "/api/ping",
  "/api/start",
  "/api/status",
  "/api/cancel",
  "/api/dancers",
  "/api/couples",
  "/api/texas",
  "/api/catalog",
  "/api/competition",
]);
const directory = resolve(root, "dist-preview");
createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://127.0.0.1");
    if (allowed.has(url.pathname)) {
      if (!["GET", "POST"].includes(req.method)) {
        res.writeHead(405).end();
        return;
      }
      const chunks = [];
      let size = 0;
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 16384) {
          res.writeHead(413).end();
          return;
        }
        chunks.push(chunk);
      }
      const body = Buffer.concat(chunks);
      const target = new URL(url.pathname + url.search, base),
        makeRequest = target.protocol === "https:" ? httpsRequest : httpRequest;
      const upstream = makeRequest(
        target,
        {
          method: req.method,
          headers: {
            "Content-Type": "application/json",
            "Content-Length": body.length,
            "X-Visitor": req.headers["x-visitor"] || "",
          },
          timeout: 25000,
        },
        (response) => {
          res.writeHead(response.statusCode || 502, {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
          });
          response.pipe(res);
        },
      );
      upstream.on("timeout", () => upstream.destroy());
      upstream.on("error", () => {
        if (!res.headersSent) res.writeHead(502);
        res.end(
          JSON.stringify({
            error: "Start the local Docker app to preview results.",
          }),
        );
      });
      upstream.end(body);
      return;
    }
    const file = resolve(
      directory,
      "." +
        decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname),
    );
    if (!file.startsWith(directory + sep)) {
      res.writeHead(403).end();
      return;
    }
    let data;
    try {
      data = await readFile(file);
    } catch (error) {
      if (error.code !== "ENOENT" || extname(file)) throw error;
      data = await readFile(resolve(directory, "index.html"));
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(data);
      return;
    }
    const type =
      {
        ".html": "text/html",
        ".js": "text/javascript",
        ".png": "image/png",
        ".ico": "image/x-icon",
        ".json": "application/json",
      }[extname(file)] || "application/octet-stream";
    res.writeHead(200, { "Content-Type": type });
    res.end(data);
  } catch {
    res.writeHead(404).end("Not found");
  }
}).listen(8081, "127.0.0.1", () =>
  console.log(
    "Mobile preview: http://127.0.0.1:8081 (OAuth requires a native development build).",
  ),
);
