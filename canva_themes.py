"""
Canva-Extracted Themes
These themes are extracted from your uploaded Canva PowerPoint files
"""

CANVA_THEMES = {
    'canva_dark_gray': {
        'name': 'Canva Dark Gray',
        'background': '#2f2f2f',
        'title_color': '#d9d9d9',
        'text_color': '#a6a6a6',
        'accent_color': '#ffffff',
        'title_font': 'Calibri',  # Fallback for 'Radley Italics'
        'body_font': 'Calibri',
        'title_size': 44,
        'body_size': 18,
        'has_image_placeholder': True,
        'image_position': {
            'left': 6.5,  # inches from left
            'top': 1.5,   # inches from top
            'width': 3.0,  # width in inches
            'height': 4.0  # height in inches
        }
    },
    
    'canva_navy_blue': {
        'name': 'Canva Navy Blue',
        'background': '#001f3f',
        'title_color': '#ffffff',
        'text_color': '#ffffff',
        'accent_color': '#4a90e2',
        'title_font': 'Arial',  # Fallback for 'TT Fors'
        'body_font': 'Arial',
        'title_size': 44,
        'body_size': 18,
        'has_image_placeholder': True,
        'image_position': {
            'left': 6.5,
            'top': 1.5,
            'width': 3.0,
            'height': 4.0
        }
    },
    
    'canva_bold_red': {
        'name': 'Canva Bold Red',
        'background': '#ff0000',
        'title_color': '#ffffff',
        'text_color': '#ffffff',
        'accent_color': '#ffcccb',
        'title_font': 'Arial Bold',  # Fallback for 'Antique Olive'
        'body_font': 'Arial',
        'title_size': 44,
        'body_size': 18,
        'has_image_placeholder': True,
        'image_position': {
            'left': 6.5,
            'top': 1.5,
            'width': 3.0,
            'height': 4.0
        }
    },
    
    'canva_orange': {
        'name': 'Canva Orange',
        'background': '#d35400',
        'title_color': '#ffffff',
        'text_color': '#f0f0f0',
        'accent_color': '#ffa500',
        'title_font': 'Arial',
        'body_font': 'Calibri',
        'title_size': 44,
        'body_size': 18,
        'has_image_placeholder': True,
        'image_position': {
            'left': 6.5,
            'top': 1.5,
            'width': 3.0,
            'height': 4.0
        }
    },
    
    'canva_purple': {
        'name': 'Canva Purple',
        'background': '#5a2e7d',
        'title_color': '#ffffff',
        'text_color': '#ffffff',
        'accent_color': '#9b59b6',
        'title_font': 'Arial Bold',  # Fallback for 'Antique Olive'
        'body_font': 'Arial',
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
}

def get_canva_theme(theme_name):
    """Get theme configuration by name"""
    return CANVA_THEMES.get(theme_name, CANVA_THEMES['canva_navy_blue'])

def list_canva_themes():
    """List all available Canva themes"""
    return [
        {'id': key, 'name': theme['name'], 'background': theme['background']}
        for key, theme in CANVA_THEMES.items()
    ]
