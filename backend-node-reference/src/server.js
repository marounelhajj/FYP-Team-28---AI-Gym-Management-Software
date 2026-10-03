const express = require("express");
const cors = require("cors");
const membersRouter = require("./routes/members");

const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors());
app.use(express.json());

app.get("/api/health", (req, res) => {
  res.json({ status: "ok" });
});

app.use("/api/members", membersRouter);

app.use((req, res) => {
  res.status(404).json({ error: "Not found" });
});

app.listen(PORT, () => {
  console.log(`Gym management backend listening on http://localhost:${PORT}`);
});
