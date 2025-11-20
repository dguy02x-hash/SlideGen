# Technical Guide: Adding Canva Theme Support

## Overview

While you can't directly import Canva's AI-generated themes, you can implement a system to use Canva-inspired themes in your presentations.

---

## Method 1: Template-Based Approach (Easiest)

### Step 1: Create Template in Canva
1. Design your ideal presentation in Canva
2. Add placeholder slides with your preferred layouts
3. Export as PowerPoint (.pptx)

### Step 2: Use as Template in Code

```python
from pptx import Presentation
from copy import deepcopy

def generate_from_canva_template(template_path, content):
    """Generate presentation using Canva-exported template"""
    
    # Load the Canva template
    prs = Presentation(template_path)
    
    # The first slide usually has the theme
    template_slide_layout = prs.slides[0].slide_layout
    
    # Clear existing slides except first (keep for reference)
    slides_to_remove = list(prs.slides)[1:]
    for slide in slides_to_remove:
        rId = prs.slides._sldIdLst[prs.slides.index(slide)].rId
        prs.part.drop_rel(rId)
        del prs.slides._sldIdLst[prs.slides.index(slide)]
    
    # Add new content slides using the template's styling
    for section in content['sections']:
        slide = prs.slides.add_slide(template_slide_layout)
        # Add your content here
        # The slide will automatically use the template's theme
    
    return prs
```

---

## Method 2: Extract and Configure (More Flexible)

### Step 1: Extract Theme from Canva

Open your Canva design and note:

**Colors**:
- Background: `#FFFFFF` or custom
- Primary: Click color → See hex code
- Secondary: Click color → See hex code
- Text: Usually `#000000` or dark gray
- Accent: Highlight color

**Fonts**:
- Title font: Look in text settings
- Body font: Look in text settings

**Layout**:
- Margins and spacing
- Title placement
- Content alignment

### Step 2: Add to Your Server

Create a `canva_themes.py` file:

```python
"""
Canva-Inspired Custom Themes
Extract colors and fonts from Canva designs
"""

CANVA_THEMES = {
    'Canva Modern Blue': {
        'background': '#F8FAFC',
        'title_color': '#1E40AF',
        'text_color': '#1F2937',
        'accent_color': '#3B82F6',
        'secondary_color': '#93C5FD',
        'title_font': 'Montserrat',
        'body_font': 'Open Sans',
        'title_size': 44,
        'body_size': 18,
        'spacing': {
            'title_top': 0.5,
            'content_top': 1.5,
            'bullet_spacing': 0.3
        }
    },
    
    'Canva Minimalist': {
        'background': '#FFFFFF',
        'title_color': '#000000',
        'text_color': '#374151',
        'accent_color': '#F59E0B',
        'secondary_color': '#FCD34D',
        'title_font': 'Helvetica',
        'body_font': 'Helvetica',
        'title_size': 48,
        'body_size': 20,
        'spacing': {
            'title_top': 0.8,
            'content_top': 2.0,
            'bullet_spacing': 0.4
        }
    },
    
    'Canva Corporate': {
        'background': '#1F2937',
        'title_color': '#FFFFFF',
        'text_color': '#E5E7EB',
        'accent_color': '#10B981',
        'secondary_color': '#34D399',
        'title_font': 'Arial',
        'body_font': 'Arial',
        'title_size': 40,
        'body_size': 18,
        'spacing': {
            'title_top': 0.6,
            'content_top': 1.6,
            'bullet_spacing': 0.35
        }
    }
}

def get_canva_theme(theme_name):
    """Get theme configuration"""
    return CANVA_THEMES.get(theme_name, CANVA_THEMES['Canva Modern Blue'])
```

### Step 3: Apply Theme in Presentation

In your `pptx_generator.py` or similar:

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from canva_themes import get_canva_theme

def apply_canva_theme(prs, theme_name):
    """Apply Canva-inspired theme to presentation"""
    theme = get_canva_theme(theme_name)
    
    for slide in prs.slides:
        # Set background
        background = slide.background
        fill = background.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor.from_string(theme['background'][1:])
        
        # Apply to all text shapes
        for shape in slide.shapes:
            if hasattr(shape, "text_frame"):
                text_frame = shape.text_frame
                
                # Check if it's a title
                if shape.name.startswith('Title'):
                    for paragraph in text_frame.paragraphs:
                        paragraph.font.name = theme['title_font']
                        paragraph.font.size = Pt(theme['title_size'])
                        paragraph.font.color.rgb = RGBColor.from_string(
                            theme['title_color'][1:]
                        )
                else:
                    # Body text
                    for paragraph in text_frame.paragraphs:
                        paragraph.font.name = theme['body_font']
                        paragraph.font.size = Pt(theme['body_size'])
                        paragraph.font.color.rgb = RGBColor.from_string(
                            theme['text_color'][1:]
                        )

def create_slide_with_canva_theme(prs, theme_name, title, content):
    """Create a slide with Canva theme applied"""
    theme = get_canva_theme(theme_name)
    
    # Add blank slide
    blank_layout = prs.slide_layouts[6]  # Blank layout
    slide = prs.slides.add_slide(blank_layout)
    
    # Set background
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(theme['background'][1:])
    
    # Add title
    title_box = slide.shapes.add_textbox(
        Inches(0.5),
        Inches(theme['spacing']['title_top']),
        Inches(9),
        Inches(1)
    )
    title_frame = title_box.text_frame
    title_frame.text = title
    title_para = title_frame.paragraphs[0]
    title_para.font.name = theme['title_font']
    title_para.font.size = Pt(theme['title_size'])
    title_para.font.bold = True
    title_para.font.color.rgb = RGBColor.from_string(theme['title_color'][1:])
    
    # Add content
    content_box = slide.shapes.add_textbox(
        Inches(0.5),
        Inches(theme['spacing']['content_top']),
        Inches(9),
        Inches(4)
    )
    content_frame = content_box.text_frame
    
    for bullet in content:
        p = content_frame.add_paragraph()
        p.text = bullet
        p.level = 0
        p.font.name = theme['body_font']
        p.font.size = Pt(theme['body_size'])
        p.font.color.rgb = RGBColor.from_string(theme['text_color'][1:])
    
    return slide
```

### Step 4: Add to Your API

In your server file, add endpoint to list available Canva themes:

```python
@app.route('/api/themes/canva', methods=['GET'])
def get_canva_themes():
    """Get list of available Canva-inspired themes"""
    from canva_themes import CANVA_THEMES
    
    themes = []
    for name, config in CANVA_THEMES.items():
        themes.append({
            'name': name,
            'preview': {
                'background': config['background'],
                'title_color': config['title_color'],
                'accent_color': config['accent_color']
            }
        })
    
    return jsonify({'themes': themes})
```

---

## Method 3: Canva API Integration (Advanced)

### Requirements:
- Canva Pro or Enterprise account
- Canva API access (request from Canva)
- OAuth setup

### Canva API Endpoints:

```python
import requests

def fetch_canva_brand_kit(access_token):
    """Fetch brand kit from Canva API"""
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    
    response = requests.get(
        'https://api.canva.com/v1/brand-templates',
        headers=headers
    )
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Canva API error: {response.status_code}")

def convert_canva_theme(canva_theme):
    """Convert Canva brand kit to PowerPoint theme"""
    return {
        'background': canva_theme['colors']['background'],
        'title_color': canva_theme['colors']['primary'],
        'text_color': canva_theme['colors']['text'],
        'accent_color': canva_theme['colors']['accent'],
        'title_font': canva_theme['fonts']['heading'],
        'body_font': canva_theme['fonts']['body']
    }
```

**Note**: Canva API access is limited and requires approval.

---

## Practical Implementation Steps

### For Your Current System:

1. **Choose 3-5 Canva designs you like**
2. **Export each as PowerPoint**
3. **Extract color codes and fonts manually**
4. **Add to `canva_themes.py`**
5. **Update frontend to show Canva theme options**
6. **Apply themes in slide generation**

### Frontend Update:

```javascript
// Add to theme selector
const canvaThemes = [
  { id: 'canva_modern', name: 'Canva Modern Blue', preview: '#1E40AF' },
  { id: 'canva_minimal', name: 'Canva Minimalist', preview: '#000000' },
  { id: 'canva_corporate', name: 'Canva Corporate', preview: '#1F2937' }
];
```

---

## Quick Win Approach

**The fastest way to get Canva-like themes:**

1. Go to Canva
2. Create 5 presentation designs you like
3. For each one, note:
   - Background color (right-click → copy hex)
   - Title color
   - Text color
   - Accent color
   - Title font name
   - Body font name
4. Add these to a `CANVA_THEMES` dictionary
5. Use in your slide generation

**Time investment**: 30 minutes  
**Result**: 5 custom Canva-inspired themes

---

## Example: Complete Custom Theme

```python
# In canva_themes.py or your config
CUSTOM_CANVA_THEME = {
    'name': 'My Canva Theme',
    # Colors from Canva design
    'background': '#F1F5F9',      # Light blue-gray
    'title_color': '#0F172A',      # Near black
    'text_color': '#334155',       # Dark gray
    'accent_color': '#3B82F6',     # Blue
    'secondary_color': '#93C5FD',  # Light blue
    
    # Fonts from Canva
    'title_font': 'Montserrat',
    'body_font': 'Open Sans',
    
    # Sizes (adjust to your preference)
    'title_size': 44,
    'body_size': 18,
    
    # Spacing (inches)
    'title_position': {
        'left': 0.5,
        'top': 0.5,
        'width': 9,
        'height': 1
    },
    'content_position': {
        'left': 0.5,
        'top': 1.8,
        'width': 9,
        'height': 5
    }
}
```

---

## Summary

### Can you import Canva themes directly?
**No** - Canva doesn't export theme data programmatically (without API access)

### What can you do?
1. ✅ Export Canva design to PPTX and use as template
2. ✅ Manually extract colors/fonts and create custom themes
3. ✅ Request Canva API access (advanced)

### Best approach for you?
**Extract manually and add as custom themes** - takes 30 minutes, gives you full control

---

**Want to add Canva themes? Extract the colors and fonts, add to a config file, apply in your slide generation code.**
