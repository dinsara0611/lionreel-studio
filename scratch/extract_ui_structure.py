import re
import json

with open("gui/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# Find all elements with id
ids = re.findall(r'id=["\']([^"\']+)["\']', html)
print(f"Total IDs found: {len(ids)}")

# Find all steps/views
step_matches = re.findall(r'id=["\'](step[0-9_\-a-zA-Z]+|view[0-9_\-a-zA-Z]+|stage[0-9_\-a-zA-Z]+)["\']', html)
print(f"Step/Stage IDs: {step_matches}")

# Find buttons
buttons = re.findall(r'<button[^>]*id=["\']([^"\']+)["\'][^>]*>(.*?)</button>', html, re.DOTALL)
print(f"Total Buttons with IDs: {len(buttons)}")

# Find inputs
inputs = re.findall(r'<input[^>]*id=["\']([^"\']+)["\'][^>]*>', html)
print(f"Total Inputs with IDs: {len(inputs)}")

# Find selects
selects = re.findall(r'<select[^>]*id=["\']([^"\']+)["\'][^>]*>', html)
print(f"Total Selects with IDs: {len(selects)}")

# Find textareas
textareas = re.findall(r'<textarea[^>]*id=["\']([^"\']+)["\'][^>]*>', html)
print(f"Total Textareas with IDs: {len(textareas)}")

# Find modals
modals = [i for i in ids if "modal" in i.lower()]
print(f"Modals: {modals}")
