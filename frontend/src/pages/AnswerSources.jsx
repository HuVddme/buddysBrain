import React from 'react';

export default function AnswerSources({ results, retrievalNotice, isError, onViewDetails }) {
  return (
    <>
      {retrievalNotice && <p role="status" className="no-results-notice">{retrievalNotice}</p>}
      {results.length > 0 ? (
        <details className="results-container answer-sources" open={isError}>
          <summary>Sources for this answer ({results.length})</summary>
          <p>Citation labels below belong to this answer. Original passages and saved summaries are labeled separately.</p>
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
                  <button type="button" className="resource-details" onClick={() => onViewDetails(item)}>View details for {item.title}</button>
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
        </details>
      ) : (
        <div className="no-results-notice">
          <p>No internal resources matched this question.</p>
        </div>
      )}
    </>
  );
}
