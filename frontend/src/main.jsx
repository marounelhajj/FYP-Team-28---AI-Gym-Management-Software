import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import DoorKiosk from "./components/door/DoorKiosk.jsx";
import "./index.css";

// /door is the screen on a gym door reader: it signs in with a door key, not
// a staff or member account, so it's kept out of the App's login flow.
const isDoorScreen = window.location.pathname.replace(/\/+$/, "") === "/door";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>{isDoorScreen ? <DoorKiosk /> : <App />}</React.StrictMode>
);
