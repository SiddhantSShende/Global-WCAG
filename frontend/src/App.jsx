import { Routes, Route } from "react-router-dom";
import AuditWizard from "./pages/AuditWizard.jsx";
import ReviewWorkbench from "./pages/ReviewWorkbench.jsx";

export default function App() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <Routes>
        <Route path="/" element={<AuditWizard />} />
        <Route path="/review" element={<ReviewWorkbench />} />
        <Route path="*" element={<AuditWizard />} />
      </Routes>
    </>
  );
}
