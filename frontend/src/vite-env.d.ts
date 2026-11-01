/// <reference types="vite/client" />

interface Window {
  /** Injected by PyWebView when running inside the desktop shell. */
  pywebview?: {
    api?: {
      minimize?: () => Promise<void>;
      close?: () => Promise<void>;
      set_always_on_top?: (enabled: boolean) => Promise<void>;
    };
  };
}
