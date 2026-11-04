import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { auth, setUnauthorizedHandler } from "./api/client";
import Layout from "./components/Layout";
import AuditLog from "./pages/AuditLog";
import Collections from "./pages/Collections";
import Customers from "./pages/Customers";
import Invoices from "./pages/Invoices";
import Login from "./pages/Login";
import Organization from "./pages/Organization";
import Reconciliation from "./pages/Reconciliation";

export default function App() {
  const [authed, setAuthed] = useState(Boolean(auth.token));
  useEffect(() => setUnauthorizedHandler(() => setAuthed(false)), []);
  if (!authed) return <Login onLogin={() => setAuthed(true)} />;
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout onLogout={() => { auth.clear(); setAuthed(false); }} />}>
          <Route path="/organization" element={<Organization />} />
          <Route path="/customers" element={<Customers />} />
          <Route path="/invoices" element={<Invoices />} />
          <Route path="/collections" element={<Collections />} />
          <Route path="/reconciliation" element={<Reconciliation />} />
          <Route path="/audit" element={<AuditLog />} />
          <Route path="*" element={<Navigate to="/invoices" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
