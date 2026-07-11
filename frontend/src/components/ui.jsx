// Small presentational primitives built on the design-system CSS classes.
import { prettyStatus } from "../api.js";

export function Button({ variant = "", size = "", className = "", children, ...rest }) {
  const cls = ["btn", variant && `btn-${variant}`, size && `btn-${size}`, className]
    .filter(Boolean).join(" ");
  return <button className={cls} {...rest}>{children}</button>;
}

export function IconButton({ className = "", children, ...rest }) {
  return <button type="button" className={`icon-btn ${className}`} {...rest}>{children}</button>;
}

export function Card({ pad = "", className = "", children, ...rest }) {
  const cls = ["card", pad === "lg" && "card-pad-lg", "fade-in", className].filter(Boolean).join(" ");
  return <section className={cls} {...rest}>{children}</section>;
}

export function Badge({ status, children }) {
  return (
    <span className={`badge st-${status}`}>
      <span className="dot" />{children || prettyStatus(status)}
    </span>
  );
}

export function Stat({ n, label, tone = "" }) {
  return (
    <div className={`stat ${tone}`}>
      <div className="n">{n}</div>
      <div className="l">{label}</div>
    </div>
  );
}

export function Field({ label, hint, children, style }) {
  return (
    <div className="field" style={style}>
      {label && <label>{label}</label>}
      {children}
      {hint && <p className="hint">{hint}</p>}
    </div>
  );
}

export function SectionTitle({ num, children }) {
  return (
    <div className="section-title">
      <span className="num">{num}</span>
      <h2>{children}</h2>
    </div>
  );
}
