import re
with open('gui/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

print("Matching IDs in gui/index.html:")
for m in re.finditer(r'id="([^"]+)"', text):
    id_val = m.group(1)
    if any(k in id_val.lower() for k in ['step', 'create', 'render', 'export', 'library', 'clean', 'view', 'modal', 'filmstrip']):
        print(f"  {id_val}")
