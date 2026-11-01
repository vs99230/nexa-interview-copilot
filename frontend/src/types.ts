export type PipelineState = "idle" | "starting" | "listening" | "answering";

export type ServerEvent =
  | { type: "status"; state: PipelineState }
  | { type: "heard"; text: string }
  | { type: "question"; id: string; text: string }
  | { type: "answer_delta"; id: string; text: string }
  | { type: "answer_reset"; id: string }
  | { type: "answer_done"; id: string }
  | { type: "answer_error"; id: string; message: string }
  | { type: "error"; message: string }
  | { type: "stopped" };

export interface Message {
  id: string;
  question: string;
  answer: string;
  status: "answering" | "done" | "error";
  error?: string;
}

export interface StatusInfo {
  state: PipelineState;
  has_context: boolean;
  resume_chars: number;
  jd_chars: number;
  llm_providers: string[];
  whisper_model: string;
  audio_supported: boolean;
}
