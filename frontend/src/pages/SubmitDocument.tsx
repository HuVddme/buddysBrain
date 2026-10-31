import { useState, useRef, type FormEvent, type ChangeEvent } from "react";
import { PageHeader } from "../components/ui";
import {
  FileText as FiFileText,
  Check as FiCheck,
  ArrowRight as FiArrowRight,
} from "lucide-react";
import type { Resource, IngestionJob } from "../lib/types";
import { Link, useSearchParams } from "react-router-dom";
import {
  apiBaseUrl,
  serviceError,
  uploadLimitBytes,
  LIVE_TIMEOUT_MS,
} from "../lib/liveService";
import axios from "axios";
import Buddy from "../components/Buddy";
import { usePreferences } from "../components/preferences";
import SubmittedPage from "./SubmittedPage";
import DocumentJob from "./DocumentJob";

function savedJob(jobId: string | null): IngestionJob | null {
  if (jobId && /^[a-f0-9-]{36}$/.test(jobId)) return { job_id: jobId };
  try {
    const saved = JSON.parse(sessionStorage.getItem("document-job") || "null");
    return saved?.apiBase === apiBaseUrl() &&
      /^[a-f0-9-]{36}$/.test(saved?.job?.job_id)
      ? saved.job
      : null;
  } catch {
    return null;
  }
}

const SubmitDocumentPage = () => {
  const { playCompletion } = usePreferences();
  const [params, setParams] = useSearchParams();
  const [mediaType, setMediaType] = useState("");
  const [description, setDescription] = useState("");
  const [courseName, setCourseName] = useState("");
  const [title, setTitle] = useState("");
  const [uploadLink, setUploadLink] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState<Resource | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [job, setJob] = useState(() => savedJob(params.get("job")));
  const busy = useRef(false);
  const API_BASE_URL = apiBaseUrl();

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy.current || !API_BASE_URL) return;

    if (
      !mediaType ||
      !description.trim() ||
      !courseName.trim() ||
      !title.trim()
    ) {
      setError("Please fill out all fields.");
      return;
    }

    if ((mediaType === "article" || mediaType === "video") && !uploadLink) {
      setError("Please provide a link.");
      return;
    }

    if ((mediaType === "document" || mediaType === "image") && !uploadFile) {
      setError("Please upload a file.");
      return;
    }
    if (uploadFile && uploadFile.size > uploadLimitBytes()) {
      setError(
        API_BASE_URL === "/api"
          ? "Files must be 4 MB or smaller on this deployment."
          : "Files must be 10 MB or smaller.",
      );
      return;
    }

    setError("");
    busy.current = true;
    setSubmitting(true);

    try {
      if (mediaType === "article" || mediaType === "video") {
        const payload = {
          title,
          description,
          media_type: mediaType,
          media_link: uploadLink,
          course: courseName,
        };
        const { data } = await axios.post<Resource>(
          `${API_BASE_URL}/resources`,
          payload,
          { timeout: LIVE_TIMEOUT_MS },
        );
        setSubmitted(data);
        if (!data.duplicate) playCompletion();
      } else {
        const formData = new FormData();
        if (!uploadFile) return;
        formData.append("file", uploadFile);
        formData.append("title", title);
        formData.append("description", description);
        formData.append("course", courseName);

        const { data } = await axios.post<Resource | IngestionJob>(
          `${API_BASE_URL}/upload`,
          formData,
          {
            timeout: LIVE_TIMEOUT_MS,
          },
        );
        if ("job_id" in data) {
          setJob(data);
          setParams({ job: data.job_id }, { replace: true });
          try {
            sessionStorage.setItem(
              "document-job",
              JSON.stringify({
                apiBase: API_BASE_URL,
                job: { job_id: data.job_id },
              }),
            );
          } catch {
            /* Storage may be disabled. */
          }
          return;
        }
        setSubmitted(data);
        if (!data.duplicate) playCompletion();
      }
    } catch (err) {
      setError(serviceError(err));
    } finally {
      busy.current = false;
      setSubmitting(false);
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    setUploadFile(e.target.files?.[0] || null);
  };

  if (!API_BASE_URL)
    return (
      <section className="empty-panel">
        <Buddy mood="curious" />
        <h1>Uploads are not enabled yet</h1>
        <p>
          You can explore the sample lessons now. Uploads will be available once
          the live service is connected.
        </p>
        <Link to="/ask">Explore demo</Link>
      </section>
    );

  return (
    <div className="submission-page">
      {job ? (
        <DocumentJob
          initialJob={job}
          apiBase={API_BASE_URL}
          onNewUpload={() => {
            setJob(null);
            setParams({}, { replace: true });
            setUploadFile(null);
            try {
              sessionStorage.removeItem("document-job");
            } catch {
              /* Storage may be disabled. */
            }
          }}
        />
      ) : submitted ? (
        <SubmittedPage
          title={submitted.title || title}
          duplicate={submitted.duplicate}
          onNewUpload={() => {
            setSubmitted(null);
            setUploadFile(null);
            setTitle("");
            setDescription("");
            setUploadLink("");
          }}
        />
      ) : (
        <div>
          <PageHeader
            eyebrow="BUILD YOUR LIBRARY"
            title="Share a little wisdom."
          >
            Add a resource to the connected library, then ask Buddy about it.
          </PageHeader>
          <div className="submission-layout">
            <section className="submission-card">
              <div className="form-heading">
                <span className="section-icon">
                  <FiFileText aria-hidden="true" />
                </span>
                <div>
                  <h2>Resource details</h2>
                  <p>A little context makes it easier to find.</p>
                </div>
              </div>
              <form
                onSubmit={handleSubmit}
                className="form-container"
                aria-busy={submitting}
              >
                {error && (
                  <p className="error" role="alert">
                    <Buddy mood="curious" />
                    {error}
                  </p>
                )}
                <fieldset disabled={submitting} className="submission-fields">
                  <p className="form-step">
                    <span>1</span> Give it a name
                  </p>
                  {/* Title */}
                  <div className="form-group-row">
                    <label htmlFor="title">Title:</label>
                    <input
                      type="text"
                      id="title"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="e.g. A guide to binary heaps"
                      maxLength={200}
                      required
                    />
                  </div>

                  <p className="form-step">
                    <span>2</span> Choose your material
                  </p>
                  {/* Media Type */}
                  <div className="form-group-row">
                    <label htmlFor="mediaType">Media Type:</label>
                    <select
                      id="mediaType"
                      required
                      value={mediaType}
                      onChange={(e) => {
                        setMediaType(e.target.value);
                        setUploadLink("");
                        setUploadFile(null);
                      }}
                    >
                      <option value="" disabled>
                        Select type
                      </option>
                      <option value="article">Article</option>
                      <option value="video">YouTube Video</option>
                      <option value="document">Document</option>
                      <option value="image">Image</option>
                    </select>
                  </div>

                  {/* Upload Field for Link */}
                  {(mediaType === "article" || mediaType === "video") && (
                    <div className="form-group-row">
                      <label htmlFor="uploadLink">
                        {mediaType === "article"
                          ? "Article URL:"
                          : "YouTube URL:"}
                      </label>
                      <input
                        type="text"
                        id="uploadLink"
                        maxLength={2048}
                        required
                        placeholder={
                          mediaType === "article"
                            ? "E.g. https://towardsdatascience.com/..."
                            : "E.g. https://www.youtube.com/watch?v=..."
                        }
                        value={uploadLink}
                        onChange={(e) => setUploadLink(e.target.value)}
                      />
                    </div>
                  )}

                  {/* Upload Field for File */}
                  {(mediaType === "document" || mediaType === "image") && (
                    <div className="form-group-row">
                      <label htmlFor="uploadFile">
                        {mediaType === "document" ? "Document:" : "Image:"}
                      </label>
                      <input
                        type="file"
                        id="uploadFile"
                        aria-required="true"
                        accept={
                          mediaType === "document"
                            ? ".pdf,.docx,.txt"
                            : ".png,.jpg,.jpeg,.webp,.gif"
                        }
                        onChange={handleFileChange}
                      />
                      {uploadFile && (
                        <p className="file-info">Selected: {uploadFile.name}</p>
                      )}
                      <p className="file-info">
                        Maximum file size:{" "}
                        {API_BASE_URL === "/api" ? "4" : "10"} MB.
                      </p>
                    </div>
                  )}

                  <p className="form-step">
                    <span>3</span> Add a little context
                  </p>
                  {/* Course */}
                  <div className="form-group-row">
                    <label htmlFor="courseName">Course Name:</label>
                    <input
                      type="text"
                      id="courseName"
                      maxLength={200}
                      required
                      value={courseName}
                      onChange={(e) => setCourseName(e.target.value)}
                      placeholder="E.g. Intro to Computer Science"
                    />
                  </div>

                  {/* Description */}
                  <div className="form-group-row">
                    <label htmlFor="description">Description:</label>
                    <textarea
                      id="description"
                      maxLength={4000}
                      required
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      placeholder="E.g. This PDF gives a clear explanation of heaps..."
                      rows={4}
                    />
                  </div>

                  <div className="form-submit">
                    <p>All fields are required.</p>
                    <button type="submit" className="btn btn-primary">
                      {submitting ? "Submitting..." : "Submit"}
                      <FiArrowRight aria-hidden="true" />
                    </button>
                  </div>
                </fieldset>
                {submitting && (
                  <div className="thinking-state" role="status">
                    <Buddy mood="thinking" />
                    <div>
                      <p>Buddy is saving your resource…</p>
                      <div className="answer-skeleton" aria-hidden="true">
                        <span />
                        <span />
                      </div>
                    </div>
                  </div>
                )}
              </form>
            </section>
            <aside className="submission-guide">
              <section className="resource-draft" aria-label="Resource preview">
                <span className="badge">Live preview · not submitted</span>
                <FiFileText aria-hidden="true" />
                <h3>{title.trim() || "Your resource title"}</h3>
                <span className="draft-course">
                  {courseName.trim() || "Course or subject"}
                </span>
                <p>
                  {description.trim() ||
                    "A short description helps others know what’s inside."}
                </p>
                <small>
                  {uploadFile?.name ||
                    uploadLink ||
                    "Choose a file or add a link"}
                </small>
              </section>
              <p className="eyebrow">FROM NOTES TO KNOWLEDGE</p>
              <h2>What happens next?</h2>
              <ol>
                <li>
                  <span>1</span>
                  <div>
                    <strong>Add your material</strong>
                    <p>Choose a document, image, article, or YouTube video.</p>
                  </div>
                </li>
                <li>
                  <span>2</span>
                  <div>
                    <strong>Let Buddy prepare it</strong>
                    <p>
                      Documents show their processing status here. You can
                      return to check progress.
                    </p>
                  </div>
                </li>
                <li>
                  <span>3</span>
                  <div>
                    <strong>Ask and explore</strong>
                    <p>
                      Once ready, your resource can appear in library search.
                    </p>
                  </div>
                </li>
              </ol>
              <div className="upload-note">
                <FiCheck aria-hidden="true" />
                <p>
                  Documents: PDF, DOCX, or TXT.
                  <br />
                  Maximum file size: {API_BASE_URL === "/api" ? "4" : "10"} MB.
                </p>
              </div>
              <p className="privacy-note">
                This is a shared library. Only add material you have permission
                to share, and leave out personal or sensitive information.
              </p>
            </aside>
          </div>
        </div>
      )}
    </div>
  );
};

export default SubmitDocumentPage;
