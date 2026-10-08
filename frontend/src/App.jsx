import { Routes, Route } from "react-router-dom";
import MemberDirectory from "./components/MemberDirectory.jsx";
import JoinPage from "./pages/JoinPage.jsx";

// "/"     - staff-facing Member Directory (search/filter, register walk-ins)
// "/join" - public self-service signup page for prospective members
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<MemberDirectory />} />
      <Route path="/join" element={<JoinPage />} />
    </Routes>
  );
}
