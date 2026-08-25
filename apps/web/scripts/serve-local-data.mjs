import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const dataRoot = resolve(projectRoot, "artifacts/object-store");
const port = Number(process.env.DATA_PORT ?? 8787);

function headers(contentType) {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range",
    "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range, ETag",
    "Accept-Ranges": "bytes",
    "Content-Type": contentType,
  };
}

createServer(async (request, response) => {
  if (request.method === "OPTIONS") {
    response.writeHead(204, headers("text/plain"));
    response.end();
    return;
  }
  const pathname = decodeURIComponent(new URL(request.url ?? "/", "http://localhost").pathname);
  const file = resolve(dataRoot, `.${pathname}`);
  if (!file.startsWith(`${dataRoot}/`)) {
    response.writeHead(403).end();
    return;
  }
  let details;
  try {
    details = await stat(file);
  } catch {
    response.writeHead(404).end();
    return;
  }
  if (!details.isFile()) {
    response.writeHead(404).end();
    return;
  }
  const range = /^bytes=(\d*)-(\d*)$/.exec(request.headers.range ?? "");
  const contentType = file.endsWith(".json") ? "application/json" : "application/octet-stream";
  if (!range) {
    response.writeHead(200, { ...headers(contentType), "Content-Length": details.size });
    if (request.method === "HEAD") response.end();
    else createReadStream(file).pipe(response);
    return;
  }
  const start = range[1] ? Number(range[1]) : 0;
  const end = range[2] ? Math.min(Number(range[2]), details.size - 1) : details.size - 1;
  if (start > end || start >= details.size) {
    response.writeHead(416, { ...headers(contentType), "Content-Range": `bytes */${details.size}` }).end();
    return;
  }
  response.writeHead(206, { ...headers(contentType), "Content-Length": end - start + 1, "Content-Range": `bytes ${start}-${end}/${details.size}` });
  if (request.method === "HEAD") response.end();
  else createReadStream(file, { start, end }).pipe(response);
}).listen(port, "127.0.0.1", () => {
  console.log(`Local data: http://127.0.0.1:${port}`);
  console.log(`Serving: ${dataRoot}`);
});
