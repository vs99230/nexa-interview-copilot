import type { ReactNode } from "react";

interface Props {
  children?: ReactNode;
  actions?: ReactNode;
}

/** Frameless window title bar. Only the left block is a drag region so the buttons stay clickable. */
export default function TitleBar({ children, actions }: Props) {
  const api = window.pywebview?.api;
  return (
    <header className="titlebar">
      <div className="titlebar-drag pywebview-drag-region">
        <span className="logo" aria-hidden="true" />
        <span className="brand">Nexa</span>
        {children}
      </div>
      <div className="titlebar-actions">
        {actions}
        <button className="icon-btn" title="Minimize" aria-label="Minimize" onClick={() => api?.minimize?.()}>
          &minus;
        </button>
        <button className="icon-btn" title="Close" aria-label="Close" onClick={() => api?.close?.()}>
          &times;
        </button>
      </div>
    </header>
  );
}
