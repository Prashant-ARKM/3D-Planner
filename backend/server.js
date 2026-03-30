/**
 * server.js  —  3D Floor Plan Pipeline Backend
 * =============================================
 * Pure Node.js (no npm packages required).
 * Parses multipart/form-data manually using the built-in http module.
 *
 * POST /api/process
 *   Body:   multipart/form-data  { file: <image> }
 *   Returns JSON:
 *     {
 *       structure:   { outer_shell, rooms, room_count, total_area },
 *       metrics:     { ... },
 *       materials:   [ { type, material, cost_index, durability_index, reason } ],
 *       explanation: "..."
 *     }
 *
 * Requires:
 *   - Node.js >= 16
 *   - Python 3 on PATH with opencv-python-headless and numpy installed
 *     (pip install opencv-python-headless numpy)
 *
 * Run:  node server.js
 *       (default port 3000; set PORT env var to override)
 */

const http       = require('http');
const fs         = require('fs');
const path       = require('path');
const os         = require('os');
const { execFile, spawn } = require('child_process');

const PORT      = process.env.PORT || 3000;
const UPLOADS   = path.join(__dirname, 'uploads');

// Create uploads directory if absent
if (!fs.existsSync(UPLOADS)) fs.mkdirSync(UPLOADS, { recursive: true });

// ─────────────────────────────────────────────────────────────────
// Multipart parser (stdlib only — no multer/busboy)
// Parses the FIRST file field from a multipart/form-data body.
// ─────────────────────────────────────────────────────────────────
function parseMultipart(req) {
  return new Promise((resolve, reject) => {
    const contentType = req.headers['content-type'] || '';
    const match = contentType.match(/boundary=([^\s;]+)/);
    if (!match) return reject(new Error('No multipart boundary found'));

    const boundary = Buffer.from('--' + match[1]);
    const chunks   = [];

    req.on('data', chunk => chunks.push(chunk));
    req.on('error', reject);
    req.on('end', () => {
      try {
        const body     = Buffer.concat(chunks);
        const parts    = splitBuffer(body, boundary);

        for (const part of parts) {
          if (!part.length) continue;

          // Split headers from body at \r\n\r\n
          const sep   = part.indexOf('\r\n\r\n');
          if (sep === -1) continue;

          const headers    = part.slice(0, sep).toString('utf8');
          const fileBuffer = part.slice(sep + 4);

          // Strip trailing \r\n
          const fileData = fileBuffer.slice(
            0,
            fileBuffer.length > 2 &&
            fileBuffer[fileBuffer.length - 2] === 0x0d &&
            fileBuffer[fileBuffer.length - 1] === 0x0a
              ? fileBuffer.length - 2
              : fileBuffer.length
          );

          // Extract filename from Content-Disposition
          const dispMatch = headers.match(/Content-Disposition:[^\r\n]*filename="([^"]+)"/i);
          if (!dispMatch) continue;   // skip non-file fields

          const filename  = dispMatch[1].replace(/[^a-zA-Z0-9._-]/g, '_');
          const tmpPath   = path.join(UPLOADS, Date.now() + '_' + filename);
          fs.writeFileSync(tmpPath, fileData);
          return resolve({ filename, tmpPath });
        }

        reject(new Error('No file found in multipart body'));
      } catch (e) {
        reject(e);
      }
    });
  });
}

/** Split a buffer by a separator buffer. */
function splitBuffer(buf, sep) {
  const parts = [];
  let start   = 0;
  let idx;
  while ((idx = indexOf(buf, sep, start)) !== -1) {
    parts.push(buf.slice(start, idx));
    start = idx + sep.length;
    // skip \r\n after boundary
    if (buf[start] === 0x0d && buf[start + 1] === 0x0a) start += 2;
    // detect closing boundary (--)
    if (buf[start] === 0x2d && buf[start + 1] === 0x2d) break;
  }
  return parts;
}

/** Find needle Buffer in haystack Buffer starting at offset. */
function indexOf(haystack, needle, offset = 0) {
  for (let i = offset; i <= haystack.length - needle.length; i++) {
    let found = true;
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) { found = false; break; }
    }
    if (found) return i;
  }
  return -1;
}

// ─────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────
// Run a Python script and return parsed JSON output.
//
// FIX: Detect python3 vs python automatically.
//   On Windows: 'python' works. On Mac/Linux: 'python3' is correct.
//   Using the wrong one causes a silent spawn error (ENOENT).
//
// FIX: Print Python stderr to the server console.
//   materials.py logs Gemini errors to stderr — previously these
//   were silently swallowed. Now they appear in your terminal so
//   you can see exactly why Gemini is failing.
// ─────────────────────────────────────────────────────────────────
const PYTHON_BIN = process.platform === 'win32' ? 'python' : 'python3';

function runPython(scriptPath, args = [], stdinData = null) {
  return new Promise((resolve, reject) => {
    const py = spawn(PYTHON_BIN, [scriptPath, ...args]);
    const outChunks = [];
    const errChunks = [];

    py.stdout.on('data', d => outChunks.push(d));

    // FIX: Print Python stderr live to server console (shows Gemini errors)
    py.stderr.on('data', d => {
      errChunks.push(d);
      process.stderr.write('[Python] ' + d.toString());
    });

    py.on('close', code => {
      const raw = Buffer.concat(outChunks).toString('utf8').trim();
      const err = Buffer.concat(errChunks).toString('utf8').trim();

      if (!raw) {
        return reject(new Error(
          `Python script returned no output (exit ${code}).\nStderr: ${err}`
        ));
      }

      try {
        const parsed = JSON.parse(raw);
        if (parsed.error) return reject(new Error(parsed.error));
        resolve(parsed);
      } catch (e) {
        reject(new Error(`JSON parse error: ${e.message}.\nRaw output: ${raw.slice(0, 300)}`));
      }
    });

    py.on('error', (err) => {
      if (err.code === 'ENOENT') {
        reject(new Error(
          `Python not found: tried "${PYTHON_BIN}". ` +
          `Install Python 3 and ensure it is on your PATH.`
        ));
      } else {
        reject(err);
      }
    });

    if (stdinData) {
      py.stdin.write(stdinData);
      py.stdin.end();
    }
  });
}

// ─────────────────────────────────────────────────────────────────
// HTTP Server
// ─────────────────────────────────────────────────────────────────
const server = http.createServer(async (req, res) => {

  // CORS headers — allow the frontend to call us from any origin
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // ── Health check ──
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', port: PORT }));
    return;
  }

  // ── Main endpoint ──
  if (req.method === 'POST' && req.url === '/api/process') {
    let tmpPath = null;

    try {
      console.log('[/api/process] Receiving upload…');

      // 1. Parse uploaded file
      const upload = await parseMultipart(req);
      tmpPath = upload.tmpPath;
      console.log(`[/api/process] Saved to ${tmpPath}`);

      // 2. Run parser.py → structure + metrics
      console.log('[/api/process] Running parser.py…');
      const parserScript = path.join(__dirname, 'parser.py');
      const parsed = await runPython(parserScript, [tmpPath]);
      console.log(`[/api/process] Detected ${parsed.structure.room_count} rooms`);

      // 3. Run materials.py with parsed data via stdin → materials + explanation
      console.log('[/api/process] Running materials.py…');
      const materialsScript = path.join(__dirname, 'materials.py');
      const recommendations = await runPython(
        materialsScript, [], JSON.stringify(parsed)
      );

      // 4. Merge and respond
      const response = {
        structure:   parsed.structure,
        metrics:     parsed.metrics,
        materials:   recommendations.materials,
        explanation: recommendations.explanation
      };

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(response));
      console.log('[/api/process] Done ✓');

    } catch (err) {
      console.error('[/api/process] Error:', err.message);
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));

    } finally {
      // Clean up temp file
      if (tmpPath && fs.existsSync(tmpPath)) {
        try { fs.unlinkSync(tmpPath); } catch (_) {}
      }
    }
    return;
  }

  // ── 404 ──
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not found' }));
});

server.listen(PORT, () => {
  console.log(`
  ╔══════════════════════════════════════════╗
  ║  3D Floor Plan Pipeline Backend          ║
  ║  Listening on  http://localhost:${PORT}    ║
  ║  POST /api/process  (multipart image)    ║
  ║  GET  /health                            ║
  ╚══════════════════════════════════════════╝
  `);
});