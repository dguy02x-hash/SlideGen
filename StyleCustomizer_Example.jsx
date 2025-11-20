// StyleCustomizer.jsx - Example React Component
// Add this to your format/theme selection page

import React, { useState } from 'react';

const StyleCustomizer = ({ onStyleGenerated }) => {
  const [stylePrompt, setStylePrompt] = useState('');
  const [customStyle, setCustomStyle] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleGenerateStyle = async () => {
    if (!stylePrompt.trim()) {
      setError('Please enter a style description');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch('http://localhost:5000/api/presentations/style-from-prompt', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ prompt: stylePrompt })
      });

      const data = await response.json();

      if (data.success) {
        setCustomStyle(data.style);
        // Call parent component callback if provided
        if (onStyleGenerated) {
          onStyleGenerated(data.style);
        }
      } else {
        setError(data.error || 'Failed to generate style');
      }
    } catch (err) {
      setError('Network error: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const examplePrompts = [
    "Professional corporate style with blue and gray colors",
    "Creative startup pitch deck with vibrant colors",
    "Academic presentation with traditional serif fonts",
    "Modern tech company with dark backgrounds",
    "Minimalist design with lots of white space"
  ];

  return (
    <div className="style-customizer" style={{
      padding: '20px',
      border: '1px solid #ddd',
      borderRadius: '8px',
      marginBottom: '20px'
    }}>
      <h3 style={{ marginBottom: '10px' }}>🎨 Custom Style Generator</h3>
      <p style={{ color: '#666', marginBottom: '15px' }}>
        Describe your desired presentation style and let AI create a custom theme for you!
      </p>

      {/* Example Prompts */}
      <div style={{ marginBottom: '15px' }}>
        <strong>Try these examples:</strong>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '8px' }}>
          {examplePrompts.map((prompt, idx) => (
            <button
              key={idx}
              onClick={() => setStylePrompt(prompt)}
              style={{
                padding: '6px 12px',
                fontSize: '12px',
                background: '#f0f0f0',
                border: '1px solid #ccc',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              {prompt.substring(0, 30)}...
            </button>
          ))}
        </div>
      </div>

      {/* Prompt Input */}
      <textarea
        value={stylePrompt}
        onChange={(e) => setStylePrompt(e.target.value)}
        placeholder="Example: 'Professional corporate style with blue and gray colors that look trustworthy and modern'"
        rows={4}
        style={{
          width: '100%',
          padding: '12px',
          fontSize: '14px',
          border: '1px solid #ccc',
          borderRadius: '4px',
          marginBottom: '10px',
          fontFamily: 'inherit'
        }}
      />

      {/* Generate Button */}
      <button
        onClick={handleGenerateStyle}
        disabled={!stylePrompt.trim() || loading}
        style={{
          padding: '12px 24px',
          fontSize: '16px',
          background: loading ? '#ccc' : '#4CAF50',
          color: 'white',
          border: 'none',
          borderRadius: '4px',
          cursor: loading ? 'not-allowed' : 'pointer',
          fontWeight: 'bold'
        }}
      >
        {loading ? '🔄 Generating Style...' : '✨ Generate Custom Style'}
      </button>

      {/* Error Display */}
      {error && (
        <div style={{
          marginTop: '15px',
          padding: '10px',
          background: '#ffebee',
          color: '#c62828',
          borderRadius: '4px'
        }}>
          ⚠️ {error}
        </div>
      )}

      {/* Style Preview */}
      {customStyle && (
        <div style={{
          marginTop: '20px',
          padding: '20px',
          background: customStyle.background_color,
          color: customStyle.text_color,
          border: `4px solid ${customStyle.primary_color}`,
          borderRadius: '8px'
        }}>
          <h4 style={{
            color: customStyle.primary_color,
            fontFamily: customStyle.title_font,
            fontSize: '24px',
            marginBottom: '10px'
          }}>
            ✨ {customStyle.theme_name}
          </h4>

          <p style={{
            fontFamily: customStyle.body_font,
            marginBottom: '15px'
          }}>
            {customStyle.style_description}
          </p>

          {/* Color Swatches */}
          <div style={{ marginBottom: '15px' }}>
            <strong>Colors:</strong>
            <div style={{ display: 'flex', gap: '10px', marginTop: '8px' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{
                  width: '60px',
                  height: '60px',
                  background: customStyle.primary_color,
                  borderRadius: '8px',
                  border: '2px solid #ccc'
                }} />
                <small>Primary</small>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{
                  width: '60px',
                  height: '60px',
                  background: customStyle.secondary_color,
                  borderRadius: '8px',
                  border: '2px solid #ccc'
                }} />
                <small>Secondary</small>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{
                  width: '60px',
                  height: '60px',
                  background: customStyle.accent_color,
                  borderRadius: '8px',
                  border: '2px solid #ccc'
                }} />
                <small>Accent</small>
              </div>
            </div>
          </div>

          {/* Fonts */}
          <div style={{ marginBottom: '15px' }}>
            <strong>Fonts:</strong>
            <ul style={{ marginTop: '8px', marginLeft: '20px' }}>
              <li>Title: {customStyle.title_font} ({customStyle.title_size}pt)</li>
              <li>Body: {customStyle.body_font} ({customStyle.body_size}pt)</li>
            </ul>
          </div>

          {/* Style Details */}
          <div>
            <strong>Style Details:</strong>
            <ul style={{ marginTop: '8px', marginLeft: '20px' }}>
              <li>Mood: {customStyle.mood}</li>
              <li>Layout: {customStyle.layout_style}</li>
              <li>Gradients: {customStyle.use_gradients ? 'Yes' : 'No'}</li>
              <li>Shadows: {customStyle.use_shadows ? 'Yes' : 'No'}</li>
            </ul>
          </div>

          {/* Use Style Button */}
          <button
            onClick={() => {
              if (onStyleGenerated) {
                onStyleGenerated(customStyle);
              }
              alert('Custom style will be applied to your presentation!');
            }}
            style={{
              marginTop: '15px',
              padding: '10px 20px',
              background: customStyle.primary_color,
              color: '#fff',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: 'bold'
            }}
          >
            ✅ Use This Style
          </button>
        </div>
      )}
    </div>
  );
};

export default StyleCustomizer;


// ============================================
// HOW TO USE IN YOUR MAIN COMPONENT
// ============================================

/*

// In your main presentation component (e.g., PresentationCreator.jsx):

import StyleCustomizer from './StyleCustomizer';

function PresentationCreator() {
  const [customStyle, setCustomStyle] = useState(null);
  
  const handleStyleGenerated = (style) => {
    setCustomStyle(style);
    console.log('Custom style received:', style);
  };
  
  const generatePresentation = async () => {
    const payload = {
      title: presentationTitle,
      topic: presentationTopic,
      sections: presentationSections,
      theme: selectedTheme,
      notesStyle: notesStyle,
      customStyle: customStyle  // ← Include custom style here
    };
    
    const response = await fetch('/api/presentations/generate-pptx', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload)
    });
    
    // Handle file download...
  };
  
  return (
    <div>
      <h2>Create Your Presentation</h2>
      
      {/* Your existing topic/slides inputs *\/}
      
      {/* Add the Style Customizer *\/}
      <StyleCustomizer onStyleGenerated={handleStyleGenerated} />
      
      {customStyle && (
        <div className="style-selected">
          ✅ Custom style "{customStyle.theme_name}" selected!
        </div>
      )}
      
      <button onClick={generatePresentation}>
        Generate Presentation
      </button>
    </div>
  );
}

*/


// ============================================
// ALTERNATIVE: SIMPLER VERSION
// ============================================

/*
// If you want a simpler, more compact version:

function SimpleStyleGenerator() {
  const [prompt, setPrompt] = useState('');
  const [style, setStyle] = useState(null);

  const generate = async () => {
    const res = await fetch('/api/presentations/style-from-prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ prompt })
    });
    const data = await res.json();
    setStyle(data.style);
  };

  return (
    <div>
      <input 
        value={prompt}
        onChange={e => setPrompt(e.target.value)}
        placeholder="Describe your style..."
      />
      <button onClick={generate}>Generate</button>
      {style && <div>Style: {style.theme_name}</div>}
    </div>
  );
}
*/
