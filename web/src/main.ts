// Fonts: Latin subsets of Instrument Sans (400, 500, 600) for the interface and Bricolage
// Grotesque (700) for headings, both SIL OFL 1.1, bundled by Vite and served from this site
// (font-display: swap). The serif headings read like every other music app; Bricolage's
// slightly irregular, inky grotesque gives SoundStage its own voice.
import "@fontsource/instrument-sans/latin-400.css";
import "@fontsource/instrument-sans/latin-500.css";
import "@fontsource/instrument-sans/latin-600.css";
import "@fontsource/bricolage-grotesque/latin-700.css";
import "./styles/tokens.css";
import "./styles/base.css";
import { mount } from "svelte";
import App from "./App.svelte";

const app = mount(App, { target: document.getElementById("app")! });

// The service worker makes SoundStage installable and opens it offline (the library works
// without a network). Registered after load so it never competes with the first paint.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  });
}

export default app;
