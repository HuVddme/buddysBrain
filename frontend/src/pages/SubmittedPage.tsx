import { Link } from "react-router-dom";
import { FiCheck, FiArrowRight, FiPlus } from "react-icons/fi";
import { Button } from "../components/ui";

export default function SubmittedPage({
  title = "",
  duplicate = false,
  onNewUpload,
}: {
  title?: string;
  duplicate?: boolean;
  onNewUpload: () => void;
}) {
  return (
    <section className="completion-card">
      <div className="completion-icon">
        <FiCheck aria-hidden="true" />
      </div>
      <p className="eyebrow">READY FOR YOUR NEXT QUESTION</p>
      <h1>{duplicate ? "Already in the library" : "Resource saved"}</h1>
      <p className="completion-title">
        {title
          ? `"${title}" is in the library.`
          : "Your resource is in the library."}
      </p>
      <p className="muted">
        {duplicate
          ? "This file was already added. We kept the existing resource without creating a duplicate."
          : "Processing is complete. Search indexing may take a short time to catch up."}
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link to="/ask?mode=live" className="btn btn-primary">
          Ask Buddy
          <FiArrowRight aria-hidden="true" />
        </Link>
        <Button variant="secondary" onClick={onNewUpload}>
          <FiPlus aria-hidden="true" />
          Submit Another
        </Button>
      </div>
    </section>
  );
}
