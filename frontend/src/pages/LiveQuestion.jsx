import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { FaMicrophone, FaStop, FaVolumeUp, FaVolumeMute } from 'react-icons/fa';
import { apiBaseUrl, serviceError, LIVE_TIMEOUT_MS } from '../lib/liveService';

import '../styles/AskQuestion.css';

const LiveQuestion = () => {
  const [question, setQuestion] = useState('');
  const [recording, setRecording] = useState(false);
  const [messages, setMessages] = useState([]);
  const [results, setResults] = useState([]);
  const [retrievalNotice, setRetrievalNotice] = useState('');
  const [selectedResult, setSelectedResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [speechError, setSpeechError] = useState('');
  const [hasSearchResult, setHasSearchResult] = useState(false);
  const [selectedVoice, setSelectedVoice] = useState(null);

  const recognitionRef = useRef(null);
  const requestBusyRef = useRef(false);
  const requestAbortRef = useRef(null);
  const speechSupported = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
  const audioSupported = Boolean(window.speechSynthesis);
  const chatContainerRef = useRef(null);

  // Voice is optional: typed questions also work without browser speech APIs.
  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = SpeechRecognition ? new SpeechRecognition() : null;
    recognitionRef.current = recognition;
    if (recognition) {
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-US';
      recognition.onresult = (event) => {
        setQuestion(Array.from(event.results).map(result => result[0].transcript).join(' '));
      };
      recognition.onerror = () => {
        setRecording(false);
        setSpeechError('Microphone unavailable. You can type your question below.');
      };
      recognition.onend = () => setRecording(false);
    }
    const synthesis = window.speechSynthesis;
    const loadVoices = () => {
      const available = synthesis?.getVoices() || [];
      setSelectedVoice(available.find(voice => voice.name === 'Google UK English Male') || available[0] || null);
    };
    synthesis?.addEventListener('voiceschanged', loadVoices);
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
      synthesis?.removeEventListener('voiceschanged', loadVoices);
      synthesis?.cancel();
    };
  }, []);

  // Scroll chat to bottom when messages update
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [messages]);

  // Function to speak messages
  const speakMessage = (text) => {
    if (!audioEnabled || !window.speechSynthesis) return;

    // Cancel any current speech
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    if (selectedVoice) {
      utterance.voice = selectedVoice;
    }

    // Customize speech parameters
    utterance.rate = 1.15;  // Speed
    utterance.pitch = 1.0; // Pitch
    utterance.volume = 1.0; // Volume

    window.speechSynthesis.speak(utterance);
  };

  // Function to submit question & call backend
  const submitQuestion = async () => {
    if (!question.trim() || recording || requestBusyRef.current) return;
    requestBusyRef.current = true;
    requestAbortRef.current = new AbortController();

    const userMessage = { sender: 'user', text: question.trim() };
    setMessages(prev => [...prev, userMessage]);

    setIsLoading(true);
    setHasSearchResult(false);
    setResults([]);
    setRetrievalNotice('');
    setSelectedResult(null);
    setQuestion('');

    try {
      const API_BASE_URL = apiBaseUrl();
      if (!API_BASE_URL) throw new Error('Search service is not configured.');
      const response = await axios.post(`${API_BASE_URL}/search`, {
        query: userMessage.text,
      }, { timeout: LIVE_TIMEOUT_MS, signal: requestAbortRef.current.signal });

      if (requestAbortRef.current.signal.aborted) return;
      const data = response.data;
      if (!data || !Array.isArray(data.results)) throw new Error('Invalid search response');
      if (data.answer_status !== 'unavailable' && (typeof data.summary !== 'string' || !data.summary.trim())) {
        throw new Error('Invalid answer');
      }
      setResults(data.results);
      setRetrievalNotice(typeof data.retrieval_notice === 'string' ? data.retrieval_notice : '');
      setHasSearchResult(true);
      if (data.answer_status === 'unavailable') {
        const explanation = typeof data.error?.message === 'string' ? data.error.message : 'AI could not generate an answer.';
        setMessages(prev => [...prev, { sender: 'buddy', isError: true,
          text: `${explanation} Retrieved sources are available below.` }]);
        setQuestion(userMessage.text);
      } else {
        const buddyResponse = { sender: 'buddy', text: data.summary };
        setMessages(prev => [...prev, buddyResponse]);
        try { speakMessage(buddyResponse.text); } catch { /* Speech is optional. */ }
      }
    } catch (error) {
      if (error.code === 'ERR_CANCELED') return;
      setMessages(prev => [...prev, { sender: 'buddy', isError: true, text: serviceError(error) }]);
      setQuestion(userMessage.text);
    } finally {
      setIsLoading(false);
      requestBusyRef.current = false;
    }
  };



  const toggleRecording = () => {
    if (!recognitionRef.current || isLoading) return;
    setSpeechError('');
    if (recording) {
      recognitionRef.current.stop();
      // Wait for the final transcript, then let the user review and submit it.
    } else {
      try {
        window.speechSynthesis?.cancel();
        recognitionRef.current.start();
        setRecording(true);
      } catch {
        setSpeechError('Microphone unavailable. You can type your question below.');
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

  const handleResultClick = (result) => {
    setSelectedResult(result);
  };

  const handleCloseModal = () => {
    setSelectedResult(null);
  };

    const renderMessageWithLinks = (text) => {
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
        <p className="mode-notice">Live mode searches the connected resource library and asks AI for an answer. A shared usage allowance applies.</p>

        <div className="audio-toggle">
          <button
            onClick={toggleAudio}
            disabled={!audioSupported}
            className="audio-btn"
            aria-label={audioEnabled ? "Disable audio responses" : "Enable audio responses"}
            title={audioEnabled ? "Disable audio responses" : "Enable audio responses"}
          >
            {audioEnabled ? <FaVolumeUp size={20} /> : <FaVolumeMute size={20} />}
          </button>
          <span className="audio-label">{audioSupported && audioEnabled ? "Audio On" : "Audio Off"}</span>
        </div>

        {/* Question form and mic button */}
        <form onSubmit={(e) => { e.preventDefault(); submitQuestion(); }} className="form-container">
          <div className="form-group">
            <label htmlFor="question">Your question</label>
            <input
              id="question"
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
              <button type="submit" className="submit-btn" disabled={isLoading || recording || !question.trim()}>
                {isLoading ? 'Asking...' : 'Ask Buddy'}
              </button>
              <button
                type="button"
                className={`record-btn ${recording ? 'recording' : ''}`}
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
              {isLoading ?
                <div className="loading-spinner">Looking up your question...</div> :
                (speechSupported ? 'Type your question, or record it and select Ask Buddy when ready.' : 'Type your question above to ask Buddy.')
              }
            </div>
          )}
        </div>

        {/* Chat messages */}
        <div className="chat-container" ref={chatContainerRef} role="log" aria-label="Live conversation">
          {messages.length === 0 ? (
            <div className="welcome-message">
              <p>Hello! I'm Buddy the Bison. How can I help you today?</p>
              <p className="welcome-hint">Ask about course material in the connected library. If nothing matches, Buddy may offer an answer from general knowledge.</p>
            </div>
          ) : (
            messages.map((msg, index) => (
              <div key={index} className={`chat-message ${msg.sender}`}>
                <div className="message-header">
                  <strong>{msg.sender === 'user' ? 'You' : msg.isError ? 'Service notice' : 'Buddy the Bison'}</strong>
                </div>
                <div className="message-content">
                  {renderMessageWithLinks(msg.text)}
                </div>

              </div>
            ))
          )}
        </div>

        {retrievalNotice && <p role="status" className="no-results-notice">{retrievalNotice}</p>}
        {results.length > 0 ? (
          <div className="results-container">
            <h2>Retrieved resources</h2>
            <p>Original document passages and saved summaries are labeled separately below.</p>
            <div className="results-scroll">
              <ul>
                {results.map((item) => (
                  <li
                    key={item._id}
                    className="result-item hover-highlight"
                  >
                    <h3 className="result-title">{item.title}</h3>
                    {item.passages?.length ? (
                      <div className="source-passages">
                        {item.passages.map(passage => (
                          <div key={passage.citation}>
                            <p className="passage-label">[{passage.citation}] Original document passage
                              {passage.page != null && ` · Page ${passage.page}`}</p>
                            <blockquote>{passage.text}</blockquote>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <>
                        <p className="passage-label">Saved summary · not an original passage</p>
                        <p className="resource-summary">{item.summary}</p>
                      </>
                    )}
                    <button type="button" className="resource-details" onClick={() => handleResultClick(item)}>View details for {item.title}</button>
                    <p className="result-type">
                      {item.media_type === 'document' && '📄 Document'}
                      {item.media_type === 'image' && '🖼️ Image'}
                      {item.media_type === 'video' && '🎬 Video'}
                      {item.media_type === 'article' && '📰 Article'}
                    </p>
                    <a
                      href={item.media_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="result-link"
                      onClick={(e) => e.stopPropagation()}
                    >
                      View Resource
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : (
          hasSearchResult && !isLoading && (
            <div className="no-results-notice">
              <p>
                No internal resources matched this question.
              </p>
            </div>
          )
        )}


      </div> {/* .content */}

      {/* Modal for selected result */}
      {selectedResult && (
        <div className="modal-overlay" onClick={handleCloseModal}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={handleCloseModal} aria-label="Close">×</button>
            <h2>{selectedResult.title}</h2>
            <p className="result-type-badge">
              {selectedResult.media_type === 'document' && '📄 Document'}
              {selectedResult.media_type === 'image' && '🖼️ Image'}
              {selectedResult.media_type === 'video' && '🎬 Video'}
              {selectedResult.media_type === 'article' && '📰 Article'}
            </p>
            <h3>Saved resource summary</h3>
            <p className="modal-summary">{selectedResult.summary}</p>

            {/* Media Previews */}
            <div className="media-preview">
              {selectedResult.media_type === 'document' && (
                <iframe
                  src={`https://docs.google.com/gview?url=${encodeURIComponent(selectedResult.media_link)}&embedded=true`}
                  title="Document Preview"
                  width="100%"
                  height="500px"
                  style={{ border: '1px solid #ccc', borderRadius: '8px' }}
                />
              )}

              {selectedResult.media_type === 'image' && (
                <img
                  src={selectedResult.media_link}
                  alt={selectedResult.title}
                  style={{ maxWidth: '100%', maxHeight: '400px', borderRadius: '8px' }}
                />
              )}

              {selectedResult.media_type === 'video' && selectedResult.media_link.includes('youtube.com') && (
                <iframe
                  width="100%"
                  height="400px"
                  src={`https://www.youtube.com/embed/${new URL(selectedResult.media_link).searchParams.get('v')}`}
                  title="YouTube Video"
                  frameBorder="0"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                  style={{ borderRadius: '8px' }}
                />
              )}

              {selectedResult.media_type === 'video' && !selectedResult.media_link.includes('youtube.com') && (
                <video
                  controls
                  width="100%"
                  style={{ borderRadius: '8px', maxHeight: '400px' }}
                >
                  <source src={selectedResult.media_link} type="video/mp4" />
                  Your browser does not support the video tag.
                </video>
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
        </div>
      )}
    </div> // .page-container
  );
};

export default LiveQuestion;
