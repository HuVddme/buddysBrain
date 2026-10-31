import { useState, useEffect, useRef } from "react";
import { FiMessageSquare, FiArrowUp, FiBookOpen } from "react-icons/fi";
import type { Resource, ChatMessage, SearchResponse } from "../lib/types";
import axios from "axios";
import AnswerSources from "./AnswerSources";
import { youtubeEmbedUrl } from "../lib/youtube";
import { FaMicrophone, FaStop, FaVolumeUp, FaVolumeMute } from "react-icons/fa";
import { apiBaseUrl, serviceError, LIVE_TIMEOUT_MS } from "../lib/liveService";

const LiveQuestion = () => {
  const [question, setQuestion] = useState("");
  const [recording, setRecording] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selectedResult, setSelectedResult] = useState<Resource | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [speechError, setSpeechError] = useState("");
  const [selectedVoice, setSelectedVoice] =
    useState<SpeechSynthesisVoice | null>(null);
  const videoPreviewUrl =
    selectedResult?.media_type === "video"
      ? youtubeEmbedUrl(selectedResult.media_link)
      : null;

  const recognitionRef = useRef<BuddySpeechRecognition | null>(null);
  const requestBusyRef = useRef(false);
  const requestAbortRef = useRef<AbortController | null>(null);
  const speechSupported = Boolean(
    window.SpeechRecognition || window.webkitSpeechRecognition,
  );
  const audioSupported = Boolean(window.speechSynthesis);
  const questionInputRef = useRef<HTMLInputElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!selectedResult) return;
    const dialog = previewRef.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
    };
  }, [selectedResult]);

  // Voice is optional: typed questions also work without browser speech APIs.
  useEffect(() => {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = SpeechRecognition ? new SpeechRecognition() : null;
    recognitionRef.current = recognition;
    if (recognition) {
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";
      recognition.onresult = (event) => {
        setQuestion(
          Array.from(event.results)
            .map((result) => result[0].transcript)
            .join(" "),
        );
      };
      recognition.onerror = () => {
        setRecording(false);
        setSpeechError(
          "Microphone unavailable. You can type your question below.",
        );
      };
      recognition.onend = () => setRecording(false);
    }
    const synthesis = window.speechSynthesis;
    const loadVoices = () => {
      const available = synthesis?.getVoices() || [];
      setSelectedVoice(
        available.find((voice) => voice.name === "Google UK English Male") ||
          available[0] ||
          null,
      );
    };
    synthesis?.addEventListener("voiceschanged", loadVoices);
    loadVoices();
    return () => {
      requestAbortRef.current?.abort();
      if (recognition) {
        recognition.onresult = null;
        recognition.onerror = null;
        recognition.onend = null;
        recognition.abort();
      }
      recognitionRef.current = null;
      synthesis?.removeEventListener("voiceschanged", loadVoices);
      synthesis?.cancel();
    };
  }, []);

  // Scroll chat to bottom when messages update
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop =
        chatContainerRef.current.scrollHeight;
    }
  }, [messages]);

  // Function to speak messages
  const speakMessage = (text: string) => {
    if (!audioEnabled || !window.speechSynthesis) return;

    // Cancel any current speech
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    if (selectedVoice) {
      utterance.voice = selectedVoice;
    }

    // Customize speech parameters
    utterance.rate = 1.15; // Speed
    utterance.pitch = 1.0; // Pitch
    utterance.volume = 1.0; // Volume

    window.speechSynthesis.speak(utterance);
  };

  // Function to submit question & call backend
  const submitQuestion = async () => {
    if (!question.trim() || recording || requestBusyRef.current) return;
    requestBusyRef.current = true;
    requestAbortRef.current = new AbortController();

    const userMessage: ChatMessage = { sender: "user", text: question.trim() };
    setMessages((prev) => [...prev, userMessage]);

    setIsLoading(true);
    setSelectedResult(null);
    setQuestion("");

    try {
      const API_BASE_URL = apiBaseUrl();
      if (!API_BASE_URL) throw new Error("Search service is not configured.");
      const response = await axios.post<SearchResponse>(
        `${API_BASE_URL}/search`,
        {
          query: userMessage.text,
        },
        { timeout: LIVE_TIMEOUT_MS, signal: requestAbortRef.current.signal },
      );

      if (requestAbortRef.current.signal.aborted) return;
      const data = response.data;
      if (!data || !Array.isArray(data.results))
        throw new Error("Invalid search response");
      if (
        data.answer_status !== "unavailable" &&
        (typeof data.summary !== "string" || !data.summary.trim())
      ) {
        throw new Error("Invalid answer");
      }
      // Keep the evidence snapshot with its answer; citation labels restart per response.
      const evidence = {
        question: userMessage.text,
        results: data.results,
        retrievalNotice:
          typeof data.retrieval_notice === "string"
            ? data.retrieval_notice
            : "",
      };
      if (data.answer_status === "unavailable") {
        const explanation =
          typeof data.error?.message === "string"
            ? data.error.message
            : "AI could not generate an answer.";
        setMessages((prev) => [
          ...prev,
          {
            sender: "buddy",
            isError: true,
            ...evidence,
            text: `${explanation} Retrieved sources are available below.`,
          },
        ]);
        setQuestion(userMessage.text);
      } else {
        const buddyResponse: ChatMessage = {
          sender: "buddy",
          text: data.summary || "",
          ...evidence,
        };
        setMessages((prev) => [...prev, buddyResponse]);
        try {
          speakMessage(buddyResponse.text);
        } catch {
          /* Speech is optional. */
        }
      }
    } catch (error) {
      if ((error as { code?: string }).code === "ERR_CANCELED") return;
      setMessages((prev) => [
        ...prev,
        {
          sender: "buddy",
          isError: true,
          question: userMessage.text,
          text: serviceError(error),
        },
      ]);
      setQuestion(userMessage.text);
    } finally {
      setIsLoading(false);
      requestBusyRef.current = false;
    }
  };

  const toggleRecording = () => {
    if (!recognitionRef.current || isLoading) return;
    setSpeechError("");
    if (recording) {
      recognitionRef.current.stop();
      // Wait for the final transcript, then let the user review and submit it.
    } else {
      try {
        window.speechSynthesis?.cancel();
        recognitionRef.current.start();
        setRecording(true);
      } catch {
        setSpeechError(
          "Microphone unavailable. You can type your question below.",
        );
      }
    }
  };

  const toggleAudio = () => {
    const newState = !audioEnabled;
    setAudioEnabled(newState);

    if (!newState) {
      window.speechSynthesis?.cancel(); // Stop any current speech
    }
  };

  const handleResultClick = (result: Resource) => {
    setSelectedResult(result);
  };

  const handleCloseModal = () => {
    setSelectedResult(null);
  };

  const renderMessageWithLinks = (text: string) => {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    const parts = text.split(urlRegex);
    return parts.map((part, index) => {
      if (part.match(urlRegex)) {
        return (
          <a
            key={index}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
            className="message-link"
          >
            {part}
          </a>
        );
      }
      return part;
    });
  };

  return (
    <div className="live-question">
      <div className="live-content">
        <div className="live-status">
          <span className="badge">
            <span className="status-dot" />
            Live answers
          </span>
          <p>Ask about the library. Check the sources. Daily limits apply.</p>
        </div>

        {/* Chat messages */}
        <div
          className="chat-container"
          ref={chatContainerRef}
          role="log"
          aria-label="Live conversation"
        >
          {messages.length === 0 ? (
            <div className="welcome-message">
              <span className="empty-icon">
                <FiMessageSquare aria-hidden="true" />
              </span>
              <h2>What’s on your mind?</h2>
              <p className="welcome-hint">
                Ask a question about your course material. Buddy will look for
                useful sources in the library.
              </p>
              <div className="live-suggestions">
                {[
                  "Explain the difference between a heap and a binary search tree.",
                  "What makes a function continuous?",
                ].map((text) => (
                  <button
                    key={text}
                    type="button"
                    onClick={() => {
                      setQuestion(text);
                      questionInputRef.current?.focus();
                    }}
                  >
                    {text}
                    <FiArrowUp aria-hidden="true" />
                  </button>
                ))}
              </div>
              <p className="knowledge-note">
                <FiBookOpen aria-hidden="true" />
                Answers without matching sources are labeled as general
                knowledge.
              </p>
            </div>
          ) : (
            messages.map((msg, index) => (
              <div
                key={index}
                className={`chat-message ${msg.sender}`}
                role={msg.sender === "buddy" ? "article" : undefined}
                aria-label={
                  msg.sender === "buddy"
                    ? `Answer to: ${msg.question}`
                    : undefined
                }
              >
                <div className="message-header">
                  <strong>
                    {msg.sender === "user"
                      ? "You"
                      : msg.isError
                        ? "Service notice"
                        : "Buddy the Bison"}
                  </strong>
                </div>
                <div className="message-content">
                  {renderMessageWithLinks(msg.text)}
                </div>
                {msg.results && (
                  <AnswerSources
                    results={msg.results}
                    retrievalNotice={msg.retrievalNotice}
                    isError={msg.isError}
                    onViewDetails={handleResultClick}
                  />
                )}
              </div>
            ))
          )}
        </div>

        <div className="audio-toggle">
          <button
            onClick={toggleAudio}
            disabled={!audioSupported}
            className="audio-btn"
            aria-label={
              audioEnabled
                ? "Disable audio responses"
                : "Enable audio responses"
            }
            title={
              audioEnabled
                ? "Disable audio responses"
                : "Enable audio responses"
            }
          >
            {audioEnabled ? (
              <FaVolumeUp size={20} />
            ) : (
              <FaVolumeMute size={20} />
            )}
          </button>
          <span className="audio-label">
            {audioSupported && audioEnabled ? "Audio On" : "Audio Off"}
          </span>
        </div>

        {/* Question form and mic button */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submitQuestion();
          }}
          className="form-container"
        >
          <div className="form-group">
            <label htmlFor="question">Your question</label>
            <input
              id="question"
              ref={questionInputRef}
              className="question-input"
              type="text"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask about your course material..."
              disabled={isLoading || recording}
              maxLength={2000}
              required
            />
            <div className="button-group">
              <button
                type="submit"
                className="submit-btn"
                disabled={isLoading || recording || !question.trim()}
              >
                {isLoading ? "Asking..." : "Ask Buddy"}
                <FiArrowUp aria-hidden="true" />
              </button>
              <button
                type="button"
                className={`record-btn ${recording ? "recording" : ""}`}
                onClick={toggleRecording}
                disabled={!speechSupported || isLoading}
                aria-label={recording ? "Stop recording" : "Start recording"}
              >
                {recording ? <FaStop size={20} /> : <FaMicrophone size={20} />}
              </button>
            </div>
          </div>
        </form>

        {speechError && <p role="status">{speechError}</p>}
        {/* Recording indicator */}
        <div className="recording-indicator">
          {recording ? (
            <div className="pulse-recording">
              <div className="recording-animation"></div>
              Recording in progress... Click the stop button when finished.
            </div>
          ) : (
            <div>
              {isLoading ? (
                <div role="status" className="loading-spinner">
                  Looking up your question...
                </div>
              ) : speechSupported ? (
                "Type or record a question. Press Enter to send."
              ) : (
                "Press Enter to send. Check important facts against the sources."
              )}
            </div>
          )}
        </div>
      </div>{" "}
      {/* .content */}
      {/* Modal for selected result */}
      {selectedResult && (
        <dialog
          className="resource-dialog"
          ref={previewRef}
          onCancel={handleCloseModal}
          aria-labelledby="resource-preview-title"
          onClick={(e) => {
            if (e.target === e.currentTarget) handleCloseModal();
          }}
        >
          <div className="modal-content">
            <button
              className="modal-close"
              onClick={handleCloseModal}
              aria-label="Close"
            >
              ×
            </button>
            <h2 id="resource-preview-title">{selectedResult.title}</h2>
            <p className="result-type-badge">
              {selectedResult.media_type === "document" && "📄 Document"}
              {selectedResult.media_type === "image" && "🖼️ Image"}
              {selectedResult.media_type === "video" && "🎬 Video"}
              {selectedResult.media_type === "article" && "📰 Article"}
            </p>
            <h3>Saved resource summary</h3>
            <p className="modal-summary">{selectedResult.summary}</p>

            {/* Media Previews */}
            <div className="media-preview">
              {selectedResult.media_type === "document" && (
                <iframe
                  src={`https://docs.google.com/gview?url=${encodeURIComponent(selectedResult.media_link)}&embedded=true`}
                  title="Document Preview"
                  width="100%"
                  height="500px"
                  style={{ border: "1px solid #ccc", borderRadius: "8px" }}
                />
              )}

              {selectedResult.media_type === "image" && (
                <img
                  src={selectedResult.media_link}
                  alt={selectedResult.title}
                  style={{
                    maxWidth: "100%",
                    maxHeight: "400px",
                    borderRadius: "8px",
                  }}
                />
              )}

              {videoPreviewUrl && (
                <iframe
                  width="100%"
                  height="400px"
                  src={videoPreviewUrl}
                  title="YouTube Video"
                  frameBorder="0"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                  style={{ borderRadius: "8px" }}
                />
              )}

              {selectedResult.media_type === "video" && !videoPreviewUrl && (
                <p>
                  Preview unavailable for this video. Use Open Resource to view
                  the original.
                </p>
              )}
            </div>

            <a
              href={selectedResult.media_link}
              target="_blank"
              rel="noopener noreferrer"
              className="view-resource-btn"
              aria-label={`Open ${selectedResult.title} in a new tab`}
            >
              Open Resource
            </a>
          </div>
        </dialog>
      )}
    </div> // .page-container
  );
};

export default LiveQuestion;
