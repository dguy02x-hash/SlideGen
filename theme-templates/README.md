# PowerPoint Theme Templates

This directory contains template PPTX files that the system uses to generate presentations with exact styling and layouts.

## How It Works

When generating a presentation:
1. The system checks if a template file exists for the selected theme
2. If found, it clones slides from the template and fills them with AI-generated content
3. If not found, it falls back to hardcoded layouts

## Template File Structure

Each template PPTX file should contain:
- **Slide 1**: Title slide
- **Slides 2-N-1**: Content slide layouts (can have multiple variations)
- **Last Slide**: Thank you slide

The system will:
- Use slide 1 for the title slide
- Cycle through content slides (2 through N-1) for presentation content
- Use the last slide for the thank you slide

## Creating Template Files

1. Create a PowerPoint presentation with your desired theme
2. Design example slides with placeholder text:
   - Use `{{TITLE}}` or `{{PRESENTER}}` for title slide placeholders
   - Use `{{TITLE}}` or `{{SECTION_TITLE}}` for content slide titles
   - Include bullet points with `•` or `-` for content (these will be replaced)
3. Save the file as: `ThemeName.pptx` (must match theme name exactly)
4. Place it in this directory

## Example File Names

- `Sunset Orange.pptx`
- `Purple Professional.pptx`
- `Minimalist Gray.pptx`
- `Ocean Blue.pptx`
- `Simplistic Red and White.pptx`
- `Business Black and Yellow.pptx`

## Placeholder Text Conventions

### Title Slide
- `{{TITLE}}` or `Presentation Title` or `Title Here` → Replaced with presentation title
- `{{PRESENTER}}`, `{{NAME}}`, `{{AUTHOR}}`, or `Your Name` → Replaced with presenter name

### Content Slides
- `{{TITLE}}`, `{{SECTION_TITLE}}`, `Section Title`, or `Topic` → Replaced with section title
- Bullet points starting with `•` or `-` → Replaced with AI-generated content

### Thank You Slide
- No placeholders needed, cloned as-is

## Benefits Over Hardcoded Layouts

1. **Perfect Fidelity**: Uses actual PowerPoint files, not recreations
2. **Easy Updates**: Just replace the PPTX file
3. **Full Features**: Can use animations, transitions, master slides, etc.
4. **No Coding**: Add new themes without writing code
5. **Designer-Friendly**: Designers can create templates directly in PowerPoint

## Testing Your Template

1. Place your template file in this directory
2. Generate a presentation using that theme
3. The system will automatically detect and use your template
4. Check the output to ensure placeholders were replaced correctly

## Fallback Behavior

If no template file is found, the system will use the hardcoded layout methods (the previous implementation). This ensures backward compatibility.
