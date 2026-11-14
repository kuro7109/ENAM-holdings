import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installPress } from "./press";
import "@fontsource-variable/archivo/wdth.css";
import "./styles.css";

installPress();
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
