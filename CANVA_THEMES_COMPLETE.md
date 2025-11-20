# 🎨 CANVA THEMES IMPLEMENTATION COMPLETE

## ✅ What I've Done

I've extracted the themes from your 5 Canva PowerPoint files and created a complete system to use them with image placeholders.

---

## 📦 Files Created

### 1. **canva_themes.py** - Theme Configuration
Contains all 5 extracted Canva themes:
- **Canva Dark Gray** (#2f2f2f)
- **Canva Navy Blue** (#001f3f)
- **Canva Bold Red** (#ff0000)
- **Canva Orange** (#d35400)
- **Canva Purple** (#5a2e7d)

Each theme includes:
- Background color
- Title and text colors
- Accent colors
- Fonts
- Image placeholder position

### 2. **canva_slide_generator.py** - Slide Generator
Functions to create slides with:
- ✅ Canva theme colors applied
- ✅ Proper fonts
- ✅ **Blank image placeholders** (rectangle with "IMAGE" label)
- ✅ Configurable layout

### 3. **ADD_TO_SERVER.py** - Integration Code
Code snippets to add to your server for:
- Listing available Canva themes
- Generating presentations with Canva themes
- Previewing themes

### 4. **test_canva_presentation.pptx** - Demo
Working example showing Canva Navy Blue theme with image placeholder

---

## 🎨 Extracted Themes

### Theme 1: Canva Dark Gray
```python
Background: #2f2f2f (dark gray)
Title: #d9d9d9 (light gray)
Text: #a6a6a6 (medium gray)
Accent: #ffffff (white)
```

### Theme 2: Canva Navy Blue ⭐
```python
Background: #001f3f (navy blue)
Title: #ffffff (white)
Text: #ffffff (white)
Accent: #4a90e2 (light blue)
```

### Theme 3: Canva Bold Red
```python
Background: #ff0000 (red)
Title: #ffffff (white)
Text: #ffffff (white)
Accent: #ffcccb (light pink)
```

### Theme 4: Canva Orange
```python
Background: #d35400 (orange)
Title: #ffffff (white)
Text: #f0f0f0 (light gray)
Accent: #ffa500 (light orange)
```

### Theme 5: Canva Purple
```python
Background: #5a2e7d (purple)
Title: #ffffff (white)
Text: #ffffff (white)
Accent: #9b59b6 (light purple)
```

---

## 📐 Image Placeholder Details

Each slide includes a blank rectangle on the right side:
- **Position**: Right side of slide
- **Left**: 6.5 inches from left edge
- **Top**: 1.5 inches from top
- **Size**: 3.0" wide × 4.0" tall
- **Style**: Rectangle with border, labeled "IMAGE"
- **Color**: Uses theme's accent color

**Layout**:
```
┌──────────────────────────────────────┐
│  SLIDE TITLE                    ┌────┐
│                                 │IMG │
│  • Bullet point 1               │    │
│  • Bullet point 2               │    │
│  • Bullet point 3               │    │
│  • Bullet point 4               └────┘
└──────────────────────────────────────┘
```

---

## 🚀 Installation

### Step 1: Copy Files to Your Project
```bash
# Copy theme files to your project directory
cp /mnt/user-data/outputs/canva_themes.py /your/project/
cp /mnt/user-data/outputs/canva_slide_generator.py /your/project/
```

### Step 2: Install Required Package
```bash
pip install python-pptx --break-system-packages
```

### Step 3: Add to Your Server

Open `server_NATURAL_DIALOGUE.py` and add:

**At the top (imports)**:
```python
from canva_themes import get_canva_theme, list_canva_themes, CANVA_THEMES
from canva_slide_generator import generate_presentation_with_canva_themes
```

**Add new endpoint**:
```python
@app.route('/api/themes/canva', methods=['GET'])
def get_canva_themes_list():
    """Get list of available Canva themes"""
    themes = list_canva_themes()
    return jsonify({'success': True, 'themes': themes})
```

**Update generate-pptx endpoint** (see ADD_TO_SERVER.py for full code)

### Step 4: Restart Server
```bash
python server_NATURAL_DIALOGUE.py
```

---

## 💻 Usage

### Python Code Example:
```python
from canva_slide_generator import generate_presentation_with_canva_themes

sections = [
    {
        'title': 'Introduction',
        'facts': [
            'Cloud computing revolutionizes infrastructure',
            'Cost savings average 32%',
            'Global deployment enabled'
        ]
    }
]

generate_presentation_with_canva_themes(
    title='My Presentation',
    topic='Technology',
    sections=sections,
    theme_name='canva_navy_blue',  # Choose your theme
    add_images=True,  # Include image placeholders
    filename='output.pptx'
)
```

### API Usage:
```bash
# List available themes
curl http://localhost:5000/api/themes/canva

# Generate with theme
curl -X POST http://localhost:5000/api/presentations/generate-pptx \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My Presentation",
    "sections": [...],
    "theme": "canva_navy_blue",
    "add_images": true
  }'
```

---

## 🎯 Features

### ✅ What You Get:

1. **5 Canva Themes** - Exact colors from your designs
2. **Image Placeholders** - Blank spaces for adding images
3. **Proper Fonts** - Matching your Canva designs (with fallbacks)
4. **Consistent Layout** - Professional spacing and sizing
5. **Easy to Customize** - Modify positions, sizes, colors

### ✅ Customization Options:

**Change Image Position**:
```python
# In canva_themes.py
'image_position': {
    'left': 6.5,   # Change these values
    'top': 1.5,    # to move the image
    'width': 3.0,  # to resize width
    'height': 4.0  # to resize height
}
```

**Toggle Images On/Off**:
```python
generate_presentation_with_canva_themes(
    ...
    add_images=True  # Set to False to remove placeholders
)
```

**Change Theme**:
```python
theme_name='canva_dark_gray'  # or any other theme
```

---

## 📊 Theme Preview

I've generated a test presentation: `test_canva_presentation.pptx`

**Download it**: [test_canva_presentation.pptx](computer:///mnt/user-data/outputs/test_canva_presentation.pptx)

This shows:
- Canva Navy Blue theme applied
- Image placeholder on right
- Proper text colors and fonts
- Professional layout

---

## 🔧 Advanced Customization

### Add Your Own Theme:

```python
# In canva_themes.py
CANVA_THEMES['my_custom_theme'] = {
    'name': 'My Custom Theme',
    'background': '#hexcode',
    'title_color': '#hexcode',
    'text_color': '#hexcode',
    'accent_color': '#hexcode',
    'title_font': 'Font Name',
    'body_font': 'Font Name',
    'title_size': 44,
    'body_size': 18,
    'has_image_placeholder': True,
    'image_position': {
        'left': 6.5,
        'top': 1.5,
        'width': 3.0,
        'height': 4.0
    }
}
```

### Multiple Image Placeholders:

Modify `create_slide_with_canva_theme()` in `canva_slide_generator.py` to add more rectangles at different positions.

### Different Layouts:

Create variations like:
- Image on left, text on right
- Image at top, text below
- Two images side by side
- Full-screen image with text overlay

---

## 📁 Files Reference

| File | Purpose | Location |
|------|---------|----------|
| `canva_themes.py` | Theme definitions | `/mnt/user-data/outputs/` |
| `canva_slide_generator.py` | Slide generation | `/mnt/user-data/outputs/` |
| `ADD_TO_SERVER.py` | Integration code | `/mnt/user-data/outputs/` |
| `test_canva_presentation.pptx` | Example output | `/mnt/user-data/outputs/` |

---

## 🎯 Quick Start Checklist

- [ ] Download `canva_themes.py`
- [ ] Download `canva_slide_generator.py`
- [ ] Copy both files to your project directory
- [ ] Add endpoints from `ADD_TO_SERVER.py` to your server
- [ ] Install python-pptx if needed
- [ ] Restart server
- [ ] Test with: `curl http://localhost:5000/api/themes/canva`
- [ ] Generate a presentation with Canva theme
- [ ] Check the image placeholders

---

## 💡 Tips

1. **Image Placeholders**: These are just rectangles - you can replace them with actual images in PowerPoint
2. **Fonts**: Some Canva fonts aren't available, so I used similar fallbacks
3. **Colors**: Exact hex codes from your Canva files
4. **Layout**: Adjustable - change numbers in `canva_themes.py`
5. **Theme Preview**: Use the preview endpoint to test themes before generating full presentations

---

## ✅ Summary

**You now have**:
- ✅ 5 Canva themes extracted and ready to use
- ✅ Automatic image placeholder generation
- ✅ API endpoints to list and use themes
- ✅ Working example presentation
- ✅ Fully customizable system

**Your presentations will**:
- ✅ Match your Canva designs
- ✅ Have blank spaces for images
- ✅ Use correct colors and fonts
- ✅ Look professional and consistent

---

**Download the files and integrate them into your server!**

[canva_themes.py](computer:///mnt/user-data/outputs/canva_themes.py)
[canva_slide_generator.py](computer:///mnt/user-data/outputs/canva_slide_generator.py)
[ADD_TO_SERVER.py](computer:///mnt/user-data/outputs/ADD_TO_SERVER.py)
[Test Presentation](computer:///mnt/user-data/outputs/test_canva_presentation.pptx)
