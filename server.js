require('dotenv').config();
const express = require('express');
const cors = require('cors');
const multer = require('multer');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;
const UPLOADS = path.join(__dirname, 'uploads');

// Ensure uploads directory exists
if (!fs.existsSync(UPLOADS)) fs.mkdirSync(UPLOADS, { recursive: true });

// Middleware
app.use(cors()); // Critical for allowing index.html to talk to Render
app.use(express.json());
const upload = multer({ dest: 'uploads/' });

// Helper: Detect python3 vs python automatically
const PYTHON_BIN = process.platform === 'win32' ? 'python' : 'python3';

function runPython(scriptPath, args = [], stdinData = null) {
  return new Promise((resolve, reject) => {
    const py = spawn(PYTHON_BIN, [scriptPath, ...args]);
    const outChunks = [];
    const errChunks = [];

    py.stdout.on('data', d => outChunks.push(d));
    py.stderr.on('data', d => {
      errChunks.push(d);
      process.stderr.write('[Python] ' + d.toString());
    });

    py.on('close', code => {
      const raw = Buffer.concat(outChunks).toString('utf8').trim();
      const err = Buffer.concat(errChunks).toString('utf8').trim();
      if (!raw) return reject(new Error(`Python returned no output. Stderr: ${err}`));
      try {
        const parsed = JSON.parse(raw);
        if (parsed.error) return reject(new Error(parsed.error));
        resolve(parsed);
      } catch (e) {
        reject(new Error(`JSON parse error: ${e.message}`));
      }
    });

    if (stdinData) {
      py.stdin.write(stdinData);
      py.stdin.end();
    }
  });
}

// Routes
app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.post('/api/process', upload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
  const tmpPath = req.file.path;

  try {
    console.log(`[/api/process] Processing upload: ${req.file.originalname}`);

    // 1. Run parser.py
    const parserScript = path.join(__dirname, 'parser.py');
    const parsed = await runPython(parserScript, [tmpPath]);

    // 2. Run materials.py
    const materialsScript = path.join(__dirname, 'materials.py');
    const recommendations = await runPython(materialsScript, [], JSON.stringify(parsed));

    // 3. Respond
    res.json({
      structure: parsed.structure,
      metrics: parsed.metrics,
      materials: recommendations.materials,
      explanation: recommendations.explanation
    });

  } catch (err) {
    console.error('[/api/process] Error:', err.message);
    res.status(500).json({ error: err.message });
  } finally {
    if (tmpPath && fs.existsSync(tmpPath)) {
      try { fs.unlinkSync(tmpPath); } catch (_) {}
    }
  }
});

app.listen(PORT, () => {
  console.log(`🚀 Backend running on port ${PORT}`);
});
