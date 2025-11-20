# 🎨 CANVA THEMES - QUICK START

## ✅ What I Created

From your 5 Canva PowerPoint files, I extracted:
- 5 complete themes with exact colors
- Image placeholder system
- Ready-to-use slide generator

---

## 📥 Download These 3 Files

1. [**canva_themes.py**](computer:///mnt/user-data/outputs/canva_themes.py) - Theme colors & config
2. [**canva_slide_generator.py**](computer:///mnt/user-data/outputs/canva_slide_generator.py) - Slide creator
3. [**ADD_TO_SERVER.py**](computer:///mnt/user-data/outputs/ADD_TO_SERVER.py) - Integration code

---

## ⚡ Installation (2 Minutes)

```bash
# 1. Copy files to your project
cp canva_themes.py /your/project/
cp canva_slide_generator.py /your/project/

# 2. Install package
pip install python-pptx --break-system-packages

# 3. Add code from ADD_TO_SERVER.py to your server

# 4. Restart
python server_NATURAL_DIALOGUE.py
```

---

## 🎨 Your 5 Themes

1. **Canva Dark Gray** - Dark (#2f2f2f)
2. **Canva Navy Blue** - Professional (#001f3f)
3. **Canva Bold Red** - Vibrant (#ff0000)
4. **Canva Orange** - Warm (#d35400)
5. **Canva Purple** - Creative (#5a2e7d)

---

## 📐 Image Placeholders

Each slide gets a blank rectangle:
- Right side of slide
- 3" × 4" size
- Labeled "IMAGE"
- Accent color fill

```
┌────────────────────────────┐
│  TITLE             ┌────┐  │
│                    │IMG │  │
│  • Point 1         │    │  │
│  • Point 2         └────┘  │
│  • Point 3                 │
└────────────────────────────┘
```

---

## 💻 Use It

```python
from canva_slide_generator import generate_presentation_with_canva_themes

generate_presentation_with_canva_themes(
    title='My Presentation',
    topic='Business',
    sections=[...],
    theme_name='canva_navy_blue',
    add_images=True,
    filename='output.pptx'
)
```

---

## 🎯 Test It

[Download test presentation](computer:///mnt/user-data/outputs/test_canva_presentation.pptx) to see how it looks.

---

## 📚 Full Guide

[Read complete documentation](computer:///mnt/user-data/outputs/CANVA_THEMES_COMPLETE.md)

---

**That's it! Your Canva themes are ready with image placeholders.**
