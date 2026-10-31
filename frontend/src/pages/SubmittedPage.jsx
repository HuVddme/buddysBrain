import React, { useEffect, useState } from 'react';
import Confetti from 'react-confetti';
import { useWindowSize } from 'react-use';
import { Link } from 'react-router-dom';
import "../styles/SubmittedPage.css";

const SubmittedPage = ({ title = '', duplicate = false }) => {
  // Capture window size for Confetti
  const { width, height } = useWindowSize();
  const [showConfetti, setShowConfetti] = useState(true);

  // Stop confetti after 5 seconds to improve performance
  useEffect(() => {
    const timer = setTimeout(() => {
      setShowConfetti(false);
    }, 5000);

    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="landing-container">
      {showConfetti && <Confetti width={width} height={height} recycle={false} numberOfPieces={500} />}
      
      <div className="content animate-slide-in">
        <div className="success-icon">✓</div>
        <h1>{duplicate ? 'Already in the library' : 'Resource saved'}</h1>
        
        <div className="typewriter-text">
          {title ? `"${title}" is in the library.` : 'Your resource is in the library.'}
        </div>
        
        <p className="success-message">
          {duplicate ? 'This file was already added. We kept the existing resource without creating a duplicate.'
            : 'Processing is complete. Search indexing may take a short time to catch up.'}
        </p>
        
        <div className="buttons-row">
          <Link
            to="/submit"
            onClick={() => window.location.reload()}
            className="button-link"
          >
            Submit Another
          </Link>
          <Link to="/ask?mode=live" className="button-link">Ask Buddy</Link>
        </div>
      </div>
    </div>
  );
};

export default SubmittedPage;
