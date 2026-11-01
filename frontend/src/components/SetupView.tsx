import { useRef, useState } from "react";
import { startListening, submitContext } from "../api";
import type { PipelineState, StatusInfo } from "../types";
import TitleBar from "./TitleBar";

interface Props {
  info: StatusInfo | null;
  error: string | null;
  onDismissError: () => void;
  onStarted: (state: PipelineState) => void;
  onChanged: (info: StatusInfo) => void;
}

const ACCEPT = ".pdf,.docx,.txt,.md";

export default function SetupView({ info, error, onDismissError, onStarted, onChanged }: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pasteResume, setPasteResume] = useState(false);
  const [resumeText, setResumeText] = useState("");
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const hasSavedContext = Boolean(info?.has_context);
  const resumeProvided = Boolean(file) || resumeText.trim().length >= 30;
  const jdProvided = jd.trim().length >= 20;
  // Re-use what the server already holds when nothing new has been entered.
  const reuseSaved = hasSavedContext && !resumeProvided && !jdProvided;
  const canStart = !busy && (reuseSaved || (resumeProvided && jdProvided));

  const start = async () => {
    setBusy(true);
    setLocalError(null);
    onDismissError();
    try {
      if (!reuseSaved) {
        onChanged(await submitContext({ resumeFile: file, resumeText, jobDescription: jd }));
      }
      const res = await startListening();
      onChanged(res);
      onStarted(res.state);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const shownError = localError ?? error;
  const noKey = info !== null && info.llm_providers.length === 0;

  return (
    <>
      <TitleBar />
      <main className="setup">
        <section>
          <h2>1. Resume</h2>
          <div
            className={`drop ${file ? "has-file" : ""}`}
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const dropped = e.dataTransfer.files?.[0];
              if (dropped) setFile(dropped);
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.current?.click()}
          >
            {file ? <strong>{file.name}</strong> : <span>Drop a PDF, DOCX or TXT here, or click to browse</span>}
            <input
              ref={fileInput}
              type="file"
              accept={ACCEPT}
              hidden
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <button className="link-btn" onClick={() => setPasteResume((v) => !v)}>
            {pasteResume ? "Hide pasted text" : "Or paste resume text"}
          </button>
          {pasteResume && (
            <textarea
              className="field"
              rows={5}
              placeholder="Paste your resume text..."
              value={resumeText}
              onChange={(e) => setResumeText(e.target.value)}
            />
          )}
        </section>

        <section>
          <h2>2. Job description</h2>
          <textarea
            className="field"
            rows={6}
            placeholder="Paste the job description..."
            value={jd}
            onChange={(e) => setJd(e.target.value)}
          />
        </section>

        {hasSavedContext && (
          <p className="note">
            A resume ({info?.resume_chars.toLocaleString()} chars) and job description are already loaded from your last
            session. Press START to reuse them, or enter new ones above.
          </p>
        )}
        {noKey && <p className="banner warn">No LLM key found. Add GEMINI_API_KEY or GROQ_API_KEY to the .env file and restart.</p>}
        {info && !info.audio_supported && (
          <p className="banner warn">System-audio capture only works on Windows (WASAPI loopback).</p>
        )}
        {shownError && (
          <p className="banner error" role="alert">
            {shownError}
          </p>
        )}
      </main>
      <footer className="footer">
        <button className="btn primary wide" disabled={!canStart || noKey} onClick={start}>
          {busy ? "Starting..." : "START"}
        </button>
      </footer>
    </>
  );
}
