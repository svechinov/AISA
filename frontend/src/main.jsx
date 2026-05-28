import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import LoginGate from "./components/LoginGate";
import "./index.css";

const originalFetch = window.fetch;
window.fetch = async (input, init) => {
  const token = localStorage.getItem("aibizos_auth_token");
  let headers = new Headers(init?.headers);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const newInit = { ...init, headers };
  
  const response = await originalFetch(input, newInit);
  
  if (response.status === 401 && !response.url.includes("/api/auth/login")) {
    window.dispatchEvent(new Event("aibizos:unauthorized"));
  }
  
  return response;
};

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <LoginGate>
      <App />
    </LoginGate>
  </React.StrictMode>,
);
