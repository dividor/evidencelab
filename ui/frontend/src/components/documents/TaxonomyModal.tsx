import React from 'react';

interface TaxonomyValue {
  code: string;
  name: string;
  reason?: string;
}

interface TaxonomyModalProps {
  isOpen: boolean;
  onClose: () => void;
  taxonomyValue: TaxonomyValue | null;
  definition: string;
  taxonomyName: string;
}

export const TaxonomyModal: React.FC<TaxonomyModalProps> = ({
  isOpen,
  onClose,
  taxonomyValue,
  definition,
  taxonomyName
}) => {
  if (!isOpen || !taxonomyValue) {
    return null;
  }

  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>
            {taxonomyValue.code.toUpperCase()}
            {taxonomyValue.name ? ` - ${taxonomyValue.name}` : ''}
            <em className="header-label-subtitle">(AI-generated : Experimental)</em>
          </h2>
          <div className="modal-header-actions">
            <button onClick={onClose} className="modal-close">
              ×
            </button>
          </div>
        </div>
        <div className="modal-body">
          <div className="taxonomy-content">
            {definition && (
              <section style={{ marginBottom: '1.5rem' }}>
                <h3 style={{
                  fontSize: '1rem',
                  fontWeight: 600,
                  marginBottom: '0.5rem',
                  color: '#1a1f36'
                }}>
                  Definition
                </h3>
                <p style={{
                  lineHeight: '1.6',
                  color: '#4a5568'
                }}>
                  {definition}
                </p>
              </section>
            )}

            {taxonomyValue.reason && (
              <section>
                <h3 style={{
                  fontSize: '1rem',
                  fontWeight: 600,
                  marginBottom: '0.5rem',
                  color: '#1a1f36'
                }}>
                  Why this {taxonomyName} was assigned
                </h3>
                <p style={{
                  fontStyle: 'italic',
                  color: '#666',
                  lineHeight: '1.6',
                  background: '#f7fafc',
                  padding: '1rem',
                  borderRadius: '6px',
                  borderLeft: '3px solid #0369a1'
                }}>
                  {taxonomyValue.reason}
                </p>
                <p style={{
                  fontSize: '0.875rem',
                  color: '#999',
                  marginTop: '0.5rem'
                }}>
                  AI-generated explanation
                </p>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
