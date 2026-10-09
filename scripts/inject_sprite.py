with open('gui/sprite_snippet.html', 'r', encoding='utf-8') as f:
    sprite = f.read()

with open('gui/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update favicon
html = html.replace(
    '<link rel="icon" type="image/png" href="lion_logo.png">',
    '<link rel="icon" type="image/svg+xml" href="lion_logo.svg">\n    <link rel="alternate icon" type="image/png" href="lion_logo.png">'
)

# 2. Update export-workspace-grid max-width
html = html.replace(
    'max-width: 1040px;\n            width: 100%;',
    'max-width: var(--page-max-width, 1200px);\n            width: 100%;'
)

# 3. Insert sprite right after <body class="dark-mode">
marker = '<body class="dark-mode">'
if marker in html and 'id="lionreel-icon-sprite"' not in html:
    html = html.replace(marker, marker + '\n\n    ' + sprite + '\n')
    print('Inserted SVG sprite successfully!')
else:
    print('Warning: marker not found or sprite already present')

with open('gui/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print('Updated gui/index.html successfully!')
