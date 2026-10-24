import { useCallback, useEffect, useRef, useState } from "react";
import jsQR from "jsqr";
import { fetchDoorSelf, scanAtDoor } from "../../api/doors.js";

const KEY_STORAGE = "fitnessFactory.doorKey";
const RESULT_MS = 3000;
// A camera keeps seeing the same code while it's held up - act on it once,
// and again only after it has been out of view this long.
const SAME_CODE_COOLDOWN_MS = 2000;
const SCAN_INTERVAL_MS = 200;

function readStoredKey() {
  try {
    return localStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

function storeKey(key) {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    // Private browsing: the door works until the page is reloaded.
  }
}

// Keeps the camera running and calls onCode(text) for every QR code it reads.
function CameraFeed({ onCode }) {
  const videoRef = useRef(null);
  const onCodeRef = useRef(onCode);
  const [error, setError] = useState(null);
  onCodeRef.current = onCode;

  useEffect(() => {
    let stream = null;
    let timer = null;
    let stopped = false;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { willReadFrequently: true });

    function tick() {
      const video = videoRef.current;
      if (stopped || !video) return;
      if (video.readyState === video.HAVE_ENOUGH_DATA && video.videoWidth) {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const image = context.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" });
        if (code?.data) onCodeRef.current(code.data);
      }
      timer = setTimeout(tick, SCAN_INTERVAL_MS);
    }

    if (!navigator.mediaDevices) {
      setError("No camera on this device - use a QR scanner.");
    } else {
      navigator.mediaDevices
        .getUserMedia({ video: { facingMode: "user" }, audio: false })
        .then((s) => {
          stream = s;
          if (stopped || !videoRef.current) return;
          videoRef.current.srcObject = s;
          videoRef.current.play().catch(() => {});
          tick();
        })
        .catch(() => setError("Camera unavailable - allow camera access, or use a QR scanner."));
    }

    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  if (error) return <div style={styles.cameraError}>{error}</div>;
  return (
    <div style={styles.viewport}>
      <video ref={videoRef} muted playsInline style={styles.video} aria-label="Camera preview" />
      <div style={styles.frame} />
    </div>
  );
}

// The screen on a gym door (open /door on a tablet there). It signs in with
// the door's own key - set up once from Admin Console > Doors - and every scan
// is decided by the server from the member's live membership, so access is
// granted or revoked without anyone touching the card.
export default function DoorKiosk() {
  const [key, setKey] = useState("");
  const [door, setDoor] = useState(null);
  const [connecting, setConnecting] = useState(() => Boolean(readStoredKey()));
  const [setupError, setSetupError] = useState(null);
  const [keyInput, setKeyInput] = useState("");
  const [result, setResult] = useState(null); // { granted, message }
  const [typed, setTyped] = useState("");
  const busy = useRef(false);
  const lastCode = useRef({ code: null, at: 0 });
  const clearTimer = useRef(null);
  const scannerInput = useRef(null);

  function disconnect(message) {
    storeKey("");
    setKey("");
    setDoor(null);
    setResult(null);
    setSetupError(message);
  }

  async function connect(candidate) {
    setConnecting(true);
    setSetupError(null);
    try {
      const info = await fetchDoorSelf(candidate);
      storeKey(candidate);
      setKey(candidate);
      setDoor(info);
      setKeyInput("");
    } catch (err) {
      storeKey("");
      if (err.status === 401) setSetupError("That key doesn't match any door reader.");
      else if (err.status === 403) setSetupError("This door reader has been disabled. Ask an administrator.");
      else setSetupError("Can't reach the gym system. Check the connection and try again.");
    } finally {
      setConnecting(false);
    }
  }

  useEffect(() => {
    const stored = readStoredKey();
    if (stored) connect(stored);
    return () => clearTimeout(clearTimer.current);
  }, []);

  const handleCode = useCallback(
    async (raw) => {
      const code = raw.trim();
      if (!code) return;
      const now = Date.now();
      const last = lastCode.current;
      lastCode.current = { code, at: now };
      if (busy.current || (code === last.code && now - last.at < SAME_CODE_COOLDOWN_MS)) return;
      busy.current = true;

      let decision;
      try {
        decision = await scanAtDoor(key, code);
      } catch (err) {
        if (err.status === 401 || err.status === 403) {
          disconnect("This door reader was disabled or its key was replaced. Enter the new key to continue.");
          busy.current = false;
          return;
        }
        // The server can't be reached: entrances fail closed.
        decision = { granted: false, message: "Can't reach the gym system right now. Please see the front desk." };
      }
      busy.current = false;
      setResult(decision);
      clearTimeout(clearTimer.current);
      clearTimer.current = setTimeout(() => setResult(null), RESULT_MS);
      scannerInput.current?.focus();
    },
    [key],
  );

  if (!door) {
    return (
      <div style={styles.page}>
        <div style={styles.setupCard}>
          <img src="/logo-badge.png" alt="" style={styles.setupLogo} />
          <h1 style={styles.setupTitle}>Set up this door reader</h1>
          <p style={styles.setupText}>
            Paste the door key from <strong>Admin Console &rarr; Doors</strong>. It is shown once, when the door is added
            or its key is replaced.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (keyInput.trim()) connect(keyInput.trim());
            }}
          >
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="door_..."
              aria-label="Door key"
              autoComplete="off"
              style={styles.setupInput}
              autoFocus
            />
            {setupError && <div style={styles.setupError}>{setupError}</div>}
            <button type="submit" disabled={connecting || !keyInput.trim()} style={styles.setupButton}>
              {connecting ? "Connecting..." : "Connect door"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  const isExit = door.kind === "Exit";
  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div style={styles.brand}>
          <img src="/logo-badge.png" alt="" style={styles.brandLogo} />
          <div>
            <div style={styles.doorName}>{door.name}</div>
            <div style={styles.doorBranch}>Fitness Factory {door.branch}</div>
          </div>
        </div>
        <span style={{ ...styles.kindTag, background: isExit ? "#124096" : "#129638" }}>
          {isExit ? "EXIT" : "ENTRANCE"}
        </span>
      </header>

      <main style={styles.main}>
        {result ? (
          <div
            role="status"
            style={{ ...styles.resultPanel, background: result.granted ? "#129638" : "#de0b12" }}
          >
            <div style={styles.resultTitle}>{result.granted ? "DOOR OPEN" : "ACCESS DENIED"}</div>
            <div style={styles.resultMessage}>{result.message}</div>
            {!result.granted && <div style={styles.resultHint}>Please see the front desk.</div>}
          </div>
        ) : (
          <div style={styles.idle}>
            <CameraFeed onCode={handleCode} />
            <div style={styles.idleTitle}>{isExit ? "Scan your code to leave" : "Scan your membership QR code"}</div>
            <div style={styles.idleText}>Open it in the Fitness Factory app, or hold up your access card.</div>
          </div>
        )}
      </main>

      <footer style={styles.footer}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleCode(typed);
            setTyped("");
          }}
          style={styles.scannerForm}
        >
          <input
            ref={scannerInput}
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="QR scanner input (or paste a code and press Enter)"
            aria-label="QR scanner input"
            autoComplete="off"
            style={styles.scannerInput}
            autoFocus
          />
        </form>
        <button
          type="button"
          onClick={() => {
            if (window.confirm("Disconnect this door reader? It will need its key again.")) disconnect(null);
          }}
          style={styles.disconnect}
        >
          Disconnect
        </button>
      </footer>
    </div>
  );
}

const styles = {
  page: {
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    background: "#0b1a33",
    color: "#fff",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
  },
  setupCard: {
    margin: "auto",
    width: "100%",
    maxWidth: 420,
    padding: 28,
    borderRadius: 14,
    background: "#fff",
    color: "#1a1a1a",
    textAlign: "center",
  },
  setupLogo: { width: 64, height: 64 },
  setupTitle: { fontSize: 20, fontWeight: 800, margin: "12px 0 6px" },
  setupText: { fontSize: 13, color: "#555", lineHeight: 1.5, margin: "0 0 16px" },
  setupInput: {
    width: "100%",
    padding: "12px 14px",
    fontSize: 15,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    boxSizing: "border-box",
  },
  setupError: { marginTop: 10, color: "#b3261e", fontSize: 13 },
  setupButton: {
    marginTop: 14,
    width: "100%",
    padding: "12px 16px",
    fontSize: 15,
    fontWeight: 700,
    border: "none",
    borderRadius: 8,
    background: "#124096",
    color: "#fff",
    cursor: "pointer",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 28px" },
  brand: { display: "flex", alignItems: "center", gap: 12 },
  brandLogo: { width: 48, height: 48 },
  doorName: { fontSize: 20, fontWeight: 800 },
  doorBranch: { fontSize: 13, color: "#a9b7d6" },
  kindTag: { padding: "6px 14px", borderRadius: 999, fontSize: 13, fontWeight: 800, letterSpacing: 1 },
  main: { flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "0 28px" },
  idle: { display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" },
  viewport: {
    position: "relative",
    width: "min(70vw, 360px)",
    aspectRatio: "1",
    borderRadius: 18,
    overflow: "hidden",
    background: "#000",
  },
  video: { width: "100%", height: "100%", objectFit: "cover", display: "block", transform: "scaleX(-1)" },
  frame: {
    position: "absolute",
    inset: "14%",
    border: "4px solid rgba(255,255,255,0.9)",
    borderRadius: 16,
  },
  cameraError: {
    width: "min(70vw, 360px)",
    padding: "40px 20px",
    borderRadius: 18,
    background: "rgba(255,255,255,0.08)",
    color: "#c9d3ea",
    fontSize: 14,
  },
  idleTitle: { fontSize: 26, fontWeight: 800, marginTop: 24 },
  idleText: { fontSize: 15, color: "#a9b7d6", marginTop: 6 },
  resultPanel: {
    width: "100%",
    maxWidth: 640,
    padding: "56px 32px",
    borderRadius: 24,
    textAlign: "center",
    boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
  },
  resultTitle: { fontSize: 44, fontWeight: 900, letterSpacing: 2 },
  resultMessage: { fontSize: 20, fontWeight: 600, marginTop: 14, lineHeight: 1.4 },
  resultHint: { fontSize: 15, marginTop: 12, opacity: 0.9 },
  footer: { display: "flex", alignItems: "center", gap: 12, padding: "16px 28px" },
  scannerForm: { flex: 1 },
  scannerInput: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 13,
    border: "1px solid rgba(255,255,255,0.2)",
    borderRadius: 8,
    background: "rgba(255,255,255,0.06)",
    color: "#fff",
    boxSizing: "border-box",
  },
  disconnect: {
    padding: "10px 14px",
    fontSize: 13,
    border: "1px solid rgba(255,255,255,0.25)",
    borderRadius: 8,
    background: "transparent",
    color: "#c9d3ea",
    cursor: "pointer",
  },
};
