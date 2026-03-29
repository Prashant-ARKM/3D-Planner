const multer = require('multer');
const express = require('express');
const cors = require('cors');

const app = express();
const upload = multer({ dest: 'uploads/' });
// Middleware
app.use(cors());
app.use(express.json());

// Test route
app.get('/', (req, res) => {
  res.send('Backend is running');
});

// Main API route
app.post('/api/process', upload.single('file'), (req, res) => {
  console.log("Request received");

  const structure = {
    rooms: [
      { x: 0, y: 0, width: 10, height: 8 },
      { x: 10, y: 0, width: 6, height: 8 }
    ],
    walls: []
  };

  const materials = [
    { type: "outer_wall", material: "Red Brick" },
    { type: "inner_wall", material: "AAC Block" }
  ];

  const explanation = "Basic pipeline working with sample structure.";

  res.json({
    structure,
    materials,
    explanation
  });
});
// Start server
const PORT = 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});