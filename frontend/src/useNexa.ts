import { useCallback, useEffect, useReducer } from "react";
import { wsUrl } from "./api";
import type { Message, PipelineState, ServerEvent } from "./types";

const MAX_MESSAGES = 50;

interface State {
  connected: boolean;
  pipeline: PipelineState;
  heard: string;
  messages: Message[];
  error: string | null;
}

type Action =
  | { type: "connected"; value: boolean }
  | { type: "event"; event: ServerEvent }
  | { type: "pipeline"; state: PipelineState }
  | { type: "clearError" }
  | { type: "reset" };

const initial: State = { connected: false, pipeline: "idle", heard: "", messages: [], error: null };

function patch(messages: Message[], id: string, fn: (m: Message) => Message): Message[] {
  return messages.map((m) => (m.id === id ? fn(m) : m));
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "connected":
      return { ...state, connected: action.value };
    case "pipeline":
      return { ...state, pipeline: action.state };
    case "clearError":
      return { ...state, error: null };
    case "reset":
      return { ...state, heard: "", messages: [], error: null };
    case "event": {
      const e = action.event;
      switch (e.type) {
        case "status":
          return { ...state, pipeline: e.state, error: e.state === "starting" ? null : state.error };
        case "heard":
          return { ...state, heard: e.text };
        case "question": {
          const next: Message = { id: e.id, question: e.text, answer: "", status: "answering" };
          return { ...state, messages: [...state.messages, next].slice(-MAX_MESSAGES) };
        }
        case "answer_delta":
          return { ...state, messages: patch(state.messages, e.id, (m) => ({ ...m, answer: m.answer + e.text })) };
        case "answer_reset":
          return { ...state, messages: patch(state.messages, e.id, (m) => ({ ...m, answer: "" })) };
        case "answer_done":
          return { ...state, messages: patch(state.messages, e.id, (m) => ({ ...m, status: "done" })) };
        case "answer_error":
          return {
            ...state,
            messages: patch(state.messages, e.id, (m) => ({ ...m, status: "error", error: e.message })),
          };
        case "error":
          return { ...state, error: e.message };
        case "stopped":
          return { ...state, heard: "", messages: [] }; // temporary conversation memory is cleared on STOP
        default:
          return state;
      }
    }
  }
}

export function useNexa() {
  const [state, dispatch] = useReducer(reducer, initial);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;
    let attempt = 0;

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        attempt = 0;
        dispatch({ type: "connected", value: true });
      };
      ws.onmessage = (msg) => {
        try {
          dispatch({ type: "event", event: JSON.parse(msg.data) as ServerEvent });
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        dispatch({ type: "connected", value: false });
        if (!closed) timer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt++, 8000));
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  const setPipeline = useCallback((s: PipelineState) => dispatch({ type: "pipeline", state: s }), []);
  const clearError = useCallback(() => dispatch({ type: "clearError" }), []);
  const reset = useCallback(() => dispatch({ type: "reset" }), []);

  return { state, setPipeline, clearError, reset };
}
