import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/roboto/latin-400.css";
import "@fontsource/roboto/latin-500.css";
import "@fontsource/roboto/latin-700.css";
import App from "./App";
import { NotifyProvider } from "./components/notify";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <NotifyProvider>
      <App />
    </NotifyProvider>
  </React.StrictMode>,
);
