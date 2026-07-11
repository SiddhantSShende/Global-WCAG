import { Link } from "react-router-dom";
import { useTheme } from "../theme.jsx";
import { setApiKey } from "../api.js";
import { Logo, Sun, Moon, Key } from "./icons.jsx";
import { IconButton } from "./ui.jsx";

export default function TopBar({ sub, nav }) {
  const { theme, toggle } = useTheme();
  return (
    <header className="topbar">
      <div className="wrap">
        <Link className="brand" to="/" aria-label="Global WCAG home">
          <span className="logo" aria-hidden="true"><Logo /></span>
          Global WCAG <em>{sub}</em>
        </Link>
        <span className="spacer" />
        {nav}
        <IconButton onClick={setApiKey} title="Set API key" aria-label="Set API key"><Key /></IconButton>
        <IconButton onClick={toggle}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
          {theme === "dark" ? <Sun /> : <Moon />}
        </IconButton>
      </div>
    </header>
  );
}
