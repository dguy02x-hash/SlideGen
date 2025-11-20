# AI Theme Customization Guide

## Overview
SlideGen Pro now uses **AI-generated themes** based on natural language prompts. The AI automatically creates custom presentation styles that include space for images on every content slide.

## How It Works

### 1. User Describes What They Want
Users can describe their desired presentation style in natural language:
- "Professional corporate style with blue and gray colors"
- "Creative startup pitch deck with vibrant colors and modern fonts"
- "Academic presentation with traditional serif fonts"
- "Minimalist design with lots of white space"
- "Dark tech-themed presentation with neon accents"

### 2. AI Generates Custom Theme
The AI interprets the prompt and creates a complete theme configuration including:
- **Colors**: Primary, secondary, accent, background, and text colors
- **Fonts**: Title and body fonts that match the style
- **Sizes**: Appropriate font sizes for readability
- **Image Placeholders**: Style and color that complement the theme
- **Layout**: How images and text should be balanced

### 3. Image Placeholders on Every Slide
- **Title Slide**: No image placeholder (clean title presentation)
- **Content Slides**: Image placeholders in alternating positions (left, right, top, bottom)
- **Thank You Slide**: No image placeholder (clean closing)

## API Endpoint

### Generate Custom Style from Prompt
```
POST /api/presentations/style-from-prompt
```

**Request Body:**
```json
{
  "prompt": "Professional corporate presentation with blue colors"
}
```

**Response:**
```json
{
  "success": true,
  "style": {
    "theme_name": "Corporate Blue",
    "primary_color": "#1E3A8A",
    "secondary_color": "#60A5FA",
    "accent_color": "#3B82F6",
    "background_color": "#FFFFFF",
    "text_color": "#1F2937",
    "title_font": "Arial",
    "body_font": "Calibri",
    "title_size": 36,
    "body_size": 18,
    "style_description": "Clean professional theme with blue accents...",
    "mood": "professional",
    "image_placeholder_style": "light",
    "layout_preference": "balanced"
  },
  "generated_from": "Professional corporate presentation with blue colors",
  "message": "Custom style 'Corporate Blue' created successfully!"
}
```

## Image Placeholder Positions

Content slides cycle through these layouts:
1. **Right**: Image on right, text on left
2. **Left**: Image on left, text on right
3. **Top**: Image on top, text below
4. **Bottom**: Text on top, image below

This creates visual variety throughout the presentation while ensuring consistent space for images.

## Image Placeholder Styles

The AI chooses one of three placeholder styles:
- **Dark**: Dark gray placeholders (40, 40, 40) - good for light backgrounds
- **Light**: Light gray placeholders (240, 240, 240) - good for dark backgrounds
- **Themed**: Automatically adjusted based on background color

## Example Prompts and Results

### Professional/Business
**Prompt**: "Corporate presentation with navy blue and white"
- Clean design, professional fonts
- Navy backgrounds with white text
- Dark image placeholders with blue borders

### Creative/Startup
**Prompt**: "Vibrant colorful startup pitch deck"
- Bold colors, modern sans-serif fonts
- Gradient possibilities
- Colorful accent borders on images

### Academic
**Prompt**: "Traditional academic presentation for university"
- Serif fonts (Georgia, Times)
- Traditional color palette
- Subtle image borders

### Tech/Modern
**Prompt**: "Dark tech presentation with neon accents"
- Dark backgrounds, bright accent colors
- Modern fonts
- Light image placeholders with neon borders

## Benefits

✅ **User-Friendly**: Describe what you want in plain English
✅ **Consistent**: AI ensures colors work well together
✅ **Image-Ready**: Every content slide has dedicated image space
✅ **Flexible**: Supports any style from corporate to creative
✅ **Automatic**: No need to manually configure colors and fonts

## Technical Implementation

### Server Side (`server_NATURAL_DIALOGUE_COMPLETE.py`)
- `/api/presentations/style-from-prompt` endpoint generates theme
- AI validates color contrast and readability
- Returns structured JSON configuration

### PowerPoint Generator (`pptx_generator.py`)
- `ThemeGenerator` class accepts `custom_style` parameter
- Converts hex colors to PowerPoint RGBColor
- Applies custom fonts and sizes
- Creates image placeholders with theme-appropriate colors

## Notes for Developers

- Custom themes override predefined themes when provided
- All content slides automatically include image placeholders
- Image placeholder colors are calculated based on background brightness
- Font sizes ensure readability in presentations (title: 36pt, body: 18pt)
