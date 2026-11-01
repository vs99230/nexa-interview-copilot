import { useCallback, useEffect, useState } from "react";
import { getStatus, stopListening } from "./api";
import ChatView from "./components/ChatView";
import SetupView from "./components/SetupView";
import type { StatusInfo } from "./types";
import { useNexa } from "./useNexa";

export default function App() {
  const { state, setPipeline, clearError, reset } = useNexa();
  const [info, setInfo] = useState<StatusInfo | null>(null);

  const refresh = useCallback(() => {
    getStatus()
      .then(setInfo)
      .catch(() => undefined);
  }, []);

  // Re-read server status on load, on reconnect and whenever the session starts or stops.
  useEffect(refresh, [refresh, state.connected, state.pipeline]);

  const handleStop = async () => {
    try {
      await stopListening();
    } finally {
      reset();
      setPipeline("idle");
      refresh();
    }
  };

  return (
    <div className="shell">
      {state.pipeline === "idle" ? (
        <SetupView info={info} error={state.error} onDismissError={clearError} onStarted={setPipeline} onChanged={setInfo} />
      ) : (
        <ChatView state={state} onStop={handleStop} onDismissError={clearError} />
      )}
    </div>
  );
}
