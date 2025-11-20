# ADD THESE TO YOUR server_NATURAL_DIALOGUE.py FILE

# ==============================================================================
# 1. ADD THESE IMPORTS AT THE TOP
# ==============================================================================

from canva_themes import get_canva_theme, list_canva_themes, CANVA_THEMES
from canva_slide_generator import create_slide_with_canva_theme, generate_presentation_with_canva_themes


# ==============================================================================
# 2. ADD THIS ENDPOINT TO LIST AVAILABLE CANVA THEMES
# ==============================================================================

@app.route('/api/themes/canva', methods=['GET'])
def get_canva_themes_list():
    """Get list of available Canva themes"""
    try:
        themes = list_canva_themes()
        return jsonify({
            'success': True,
            'themes': themes
        })
    except Exception as e:
        logger.error(f"Error fetching Canva themes: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# 3. REPLACE OR UPDATE YOUR EXISTING generate_pptx ENDPOINT
# ==============================================================================

@app.route('/api/presentations/generate-pptx', methods=['POST'])
@login_required
# @subscription_required  # REMOVED FOR TESTING
def generate_pptx():
    """Generate the actual PowerPoint file with Canva themes"""
    try:
        data = request.json
        title = data.get('title', 'Presentation')
        topic = data.get('topic', '')
        sections = data.get('sections', [])
        theme = data.get('theme', 'canva_navy_blue')  # Default to navy blue
        notes_style = data.get('notesStyle', 'Detailed')
        add_images = data.get('add_images', True)  # Whether to include image placeholders
        
        logger.info(f"Generating PPTX: {title[:30]} with Canva theme: {theme}")
        
        # Check if it's a Canva theme
        if theme in CANVA_THEMES:
            # Use Canva theme generator
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pptx') as tmp:
                filename = generate_presentation_with_canva_themes(
                    title=title,
                    topic=topic,
                    sections=sections,
                    theme_name=theme,
                    add_images=add_images,
                    filename=tmp.name
                )
                
                from flask import send_file
                return send_file(
                    filename,
                    mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
                    as_attachment=True,
                    download_name=f"{title.replace(' ', '_')}.pptx"
                )
        else:
            # Fall back to original pptx_generator if you have one
            from pptx_generator import generate_presentation
            import tempfile
            from flask import send_file
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pptx') as tmp:
                filename = generate_presentation(
                    title=title,
                    topic=topic,
                    sections=sections,
                    theme_name=theme,
                    notes_style=notes_style,
                    filename=tmp.name
                )
                
                return send_file(
                    filename,
                    mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
                    as_attachment=True,
                    download_name=f"{title.replace(' ', '_')}.pptx"
                )
    
    except Exception as e:
        logger.error(f"PPTX generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# 4. ADD THIS TEST ENDPOINT TO PREVIEW CANVA THEMES
# ==============================================================================

@app.route('/api/themes/canva/preview', methods=['POST'])
@login_required
def preview_canva_theme():
    """Generate a preview slide with the selected Canva theme"""
    try:
        data = request.json
        theme_name = data.get('theme', 'canva_navy_blue')
        
        import tempfile
        from flask import send_file
        
        # Generate a single preview slide
        sections = [{
            'title': 'Preview Slide',
            'facts': [
                'This is how your title will look',
                'Bullet points will appear like this',
                'The image placeholder is on the right',
                'Colors match your Canva theme'
            ]
        }]
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pptx') as tmp:
            filename = generate_presentation_with_canva_themes(
                title='Theme Preview',
                topic='Preview',
                sections=sections,
                theme_name=theme_name,
                add_images=True,
                filename=tmp.name
            )
            
            return send_file(
                filename,
                mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
                as_attachment=True,
                download_name=f"preview_{theme_name}.pptx"
            )
    
    except Exception as e:
        logger.error(f"Preview generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# INSTALLATION INSTRUCTIONS
# ==============================================================================

"""
TO INSTALL:

1. Copy canva_themes.py to your project directory
2. Copy canva_slide_generator.py to your project directory
3. Add the above code snippets to your server_NATURAL_DIALOGUE.py file
4. Restart your server

Then your API will have:
- GET  /api/themes/canva - List all Canva themes
- POST /api/themes/canva/preview - Generate preview with theme
- POST /api/presentations/generate-pptx - Generate with Canva theme

Frontend can now:
- Fetch available Canva themes
- Let user select theme
- Send theme name when generating presentation
- Optionally toggle image placeholders on/off
"""
