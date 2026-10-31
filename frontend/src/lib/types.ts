export interface Passage {
  citation: string;
  text: string;
  page?: number | null;
  ordinal?: number;
}
export interface Resource {
  _id: string;
  title: string;
  summary?: string;
  course?: string;
  media_type: "document" | "image" | "video" | "article";
  media_link: string;
  passages?: Passage[];
  duplicate?: boolean;
}
export interface IngestionJob {
  job_id: string;
  title?: string;
  status?:
    | "queued"
    | "processing"
    | "retrying"
    | "succeeded"
    | "failed"
    | "cancelled";
  duplicate?: boolean;
  dispatch_pending?: boolean;
  retry_available?: boolean;
  error?: { message: string };
}
export interface ChatMessage {
  streaming?: boolean;
  sender: "user" | "buddy";
  text: string;
  question?: string;
  isError?: boolean;
  results?: Resource[];
  retrievalNotice?: string;
}
export interface SearchResponse {
  summary: string | null;
  results: Resource[];
  answer_status?: string;
  retrieval_notice?: string;
  error?: { message?: string };
}
