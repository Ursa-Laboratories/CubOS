import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const stored = localStorage.getItem("zoo-theme");
const initial = stored === "light" || stored === "dark"
  ? stored
  : (window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark");
document.documentElement.dataset.theme = initial;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
