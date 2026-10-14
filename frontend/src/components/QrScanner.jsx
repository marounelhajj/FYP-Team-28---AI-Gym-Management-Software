import { useEffect, useRef, useState } from "react";
import jsQR from "jsqr";

// Camera QR scanner for the Check-In screen (SCRUM-33). Opens the device
// camera (the back camera on a phone/tablet), decodes frames with jsQR
// and calls onScan(text) once with the first code it reads, then stops
// the camera. The decoded text is a member's check-in payload (see
// backend/members/qr.py); the backend checks it, so this never decides
// anything itself.
export default function QrScanner({ onScan, onClose }) {
  const videoRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let stream = null;
    let frame = null;
    let done = false;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { willReadFrequently: true });

    function tick() {
      const video = videoRef.current;
      if (done || !video) return;
      if (video.readyState === video.HAVE_ENOUGH_DATA && video.videoWidth) {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const image = context.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" });
        if (code?.data) {
          done = true;
          onScan(code.data);
          return;
        }
      }
      frame = requestAnimationFrame(tick);
    }

    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: "environment" }, audio: false })
      .then((s) => {
        stream = s;
        if (done || !videoRef.current) return;
        videoRef.current.srcObject = s;
        videoRef.current.play().catch(() => {});
        frame = requestAnimationFrame(tick);
      })
      .catch(() => setError("Couldn't open the camera. Allow camera access, or type the membership ID instead."));
    if (!navigator.mediaDevices) setError("This browser can't open a camera. Type the membership ID instead.");

    return () => {
      done = true;
      cancelAnimationFrame(frame);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [onScan]);

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span style={styles.title}>Scan a member's QR code</span>
        <button type="button" onClick={onClose} style={styles.close}>
          Cancel
        </button>
      </div>
      {error ? (
        <div style={styles.error}>{error}</div>
      ) : (
        <div style={styles.viewport}>
          <video ref={videoRef} muted playsInline style={styles.video} aria-label="Camera preview" />
          <div style={styles.frame} />
        </div>
      )}
      <p style={styles.hint}>Hold the code from the member's app inside the square.</p>
    </div>
  );
}

const styles = {
  panel: {
    border: "1px solid #e4e4e8",
    borderRadius: 12,
    padding: 14,
    marginBottom: 20,
    background: "#fafafa",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  title: { fontSize: 15, fontWeight: 700 },
  close: {
    padding: "6px 12px",
    fontSize: 13,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#fff",
    cursor: "pointer",
  },
  viewport: {
    position: "relative",
    borderRadius: 10,
    overflow: "hidden",
    background: "#111",
    aspectRatio: "4 / 3",
  },
  video: { width: "100%", height: "100%", objectFit: "cover", display: "block" },
  frame: {
    position: "absolute",
    top: "50%",
    left: "50%",
    width: "55%",
    aspectRatio: "1",
    transform: "translate(-50%, -50%)",
    border: "3px solid rgba(255,255,255,0.9)",
    borderRadius: 14,
    boxShadow: "0 0 0 9999px rgba(0,0,0,0.35)",
  },
  error: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  hint: { fontSize: 12, color: "#666", margin: "8px 0 0" },
};
