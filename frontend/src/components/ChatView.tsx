import { useEffect, useRef, useState } from "react";
import type { Message, PipelineState } from "../types";
import TitleBar from "./TitleBar";

interface Props {
  state: { pipeline: PipelineState; heard: string; messages: Message[]; error: string | null; connected: boolean };
  onStop: () => void;
  onDismissError: () => void;
}

const LABELS: Record<PipelineState, string> = {
  idle: "Idle",
  starting: "Starting (loading Whisper)...",
  listening: "Listening",
  answering: "Answering...",
};

export default function ChatView({ state, onStop, onDismissError }: Props) {
  const { pipeline, heard, messages, error, connected } = state;
  const scroller = useRef<HTMLDivElement>(null);
  const [stopping, setStopping] = useState(false);
  const [pinned, setPinned] = useState(false);

  // Keep the newest text in view as the answer streams in.
  const lastAnswerLength = messages.length ? messages[messages.length - 1].answer.length : 0;
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, lastAnswerLength]);

  const togglePin = () => {
    const next = !pinned;
    setPinned(next);
    void window.pywebview?.api?.set_always_on_top?.(!next);
  };

  const handleStop = () => {
    setStopping(true);
    onStop();
  };

  return (
    <>
      <TitleBar
        actions={
          <button
            className={`icon-btn ${pinned ? "active" : ""}`}
            title={pinned ? "Always on top is OFF" : "Always on top is ON"}
            aria-label="Toggle always on top"
            onClick={togglePin}
          >
            {pinned ? "○" : "●"}
          </button>
        }
      >
        <span className={`status status-${pipeline}`}>
          <span className="dot" />
          {connected ? LABELS[pipeline] : "Reconnecting..."}
        </span>
      </TitleBar>

      <div className="messages" ref={scroller}>
        {messages.length === 0 && (
          <div className="empty">
            {pipeline === "starting" ? (
              <p>Loading the speech model. The first run downloads it and can take a minute.</p>
            ) : (
              <p>Listening to system audio. When the interviewer asks a question, the answer appears here.</p>
            )}
          </div>
        )}
        {messages.map((m) => (
          <article key={m.id} className="msg">
            <p className="q">{m.question}</p>
            <div className={`a ${m.status}`}>
              {m.answer}
              {m.status === "answering" && <span className="cursor" aria-hidden="true" />}
              {m.status === "answering" && !m.answer && <span className="thinking">Thinking...</span>}
              {m.status === "error" && <p className="inline-error">{m.error ?? "Could not generate an answer."}</p>}
            </div>
          </article>
        ))}
      </div>

      {error && (
        <p className="banner error" role="alert" onClick={onDismissError} title="Click to dismiss">
          {error}
        </p>
      )}
      <footer className="footer">
        <p className="heard" title={heard}>
          {heard ? `Heard: ${heard}` : "No speech detected yet"}
        </p>
        <button className="btn danger" onClick={handleStop} disabled={stopping}>
          STOP
        </button>
      </footer>
    </>
  );
}
